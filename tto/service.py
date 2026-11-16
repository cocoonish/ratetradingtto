"""Application service: everything the web layer needs, independent of HTTP.

One dedicated engine thread (large stack, serialises all calculation work) owns the workbook engines.
The service keeps per-user input overlays, the shared desk inputs (RET curve, calendars, blotter) and a
generation counter that increases whenever something visible may have changed.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import itertools
import json
import math
import os
import queue
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as _quote

from . import auth
from . import blotter as bl
from . import bonds as bd
from . import borsaspread as bsp
from . import brokerchat as bc
from . import extras as ex
from . import layout as lay
from . import volcarry as vc
from .books import Book, formula_text, load_books, snapshot_today
from .config import Settings
from .inputs import InputError, parse_amount, parse_clipboard, parse_date, parse_input, parse_number
from .marketdata import ReplayProvider
from .marketdata.replay import snapshot_from_model
from .render import Renderer
from .store import Store, now_iso, user_key
from .views import layout as view_layout, load_views
from .xl import numfmt
from .xl.engine import Calc, Clock, big_stack_thread
from .xl.errors import XlError
from .xl.model import COLS, a1, parse_a1, parse_range
from .xl.tokenizer import index_to_col
from .marketdata.base import INVALID_FIELD, INVALID_SECURITY, NOT_APPLICABLE
from .xl.values import date_to_serial, serial_to_date

RET_TENORS = ["ON", "TN", "1W", "2W", "3W", "1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y", "18M", "2Y"]
RET_FIRST_ROW = 33


def _payer_plus(leg: Dict[str, Any]) -> Optional[float]:
    """The DV01 of an OIS leg with the desk's sign: paying fixed is plus, receiving is minus."""
    d = leg.get("dv01")
    if type(d) is not float:
        return None
    return d if leg.get("dir") == "B" else -d


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400, data: Optional[Dict[str, Any]] = None):
        Exception.__init__(self, message)
        self.status = status
        self.data = data                    # more for the page beside the message (the error of each field of a form)


class EngineThread(object):
    """Runs every calculation on one thread with a large stack (formula chains recurse deeply).

    Work waits in order of priority, first come first served within one: what a user typed goes before the header
    strip, the header before a page, a page before the background (the watch lists, warming up)."""

    WRITE, HEADER, VIEW, BACKGROUND = 0, 1, 2, 3
    _STOP = 99

    def __init__(self, name: str = "tto-engine"):
        self._q: "queue.PriorityQueue" = queue.PriorityQueue()
        self._seq = itertools.count()
        self._busy_since = 0.0                 # when the job running now began (0: idle)
        # a big stack: long chains are evaluated in one go (engine.DEEP_LIMIT deep) instead of unwound and restarted
        self._t = big_stack_thread(self._loop, name, daemon=True)

    def _loop(self) -> None:
        while True:
            _, _, item = self._q.get()
            if item is None:
                return
            fut, fn, args, kw = item
            if not fut.set_running_or_notify_cancel():
                continue
            self._busy_since = time.time()
            try:
                fut.set_result(fn(*args, **kw))
            except BaseException as exc:  # noqa: BLE001 - delivered to the caller
                fut.set_exception(exc)
            finally:
                self._busy_since = 0.0

    def queued(self) -> int:
        """Jobs waiting for the calculation thread (the one running not counted)."""
        return self._q.qsize()

    def busy_for(self) -> float:
        """Seconds the job running now has been running (0: idle)."""
        since = self._busy_since
        return time.time() - since if since else 0.0

    def submit(self, fn: Callable, *args, **kw) -> "concurrent.futures.Future":
        """``fn(*args, **kw)`` on the calculation thread, as an ordinary request (a page)."""
        return self.submit_at(self.VIEW, fn, *args, **kw)

    def submit_at(self, priority: int, fn: Callable, *args, **kw) -> "concurrent.futures.Future":
        fut: "concurrent.futures.Future" = concurrent.futures.Future()
        self._q.put((priority, next(self._seq), (fut, fn, args, kw)))
        return fut

    def call(self, fn: Callable, *args, **kw):
        return self.call_at(self.VIEW, fn, *args, **kw)

    def call_at(self, priority: int, fn: Callable, *args, **kw):
        if threading.current_thread() is self._t:
            return fn(*args, **kw)
        return self.submit_at(priority, fn, *args, **kw).result()

    def here(self) -> bool:
        """Whether the caller is the calculation thread itself."""
        return threading.current_thread() is self._t

    def waiting(self) -> int:
        return self._q.qsize()

    def stop(self) -> None:
        self._q.put((self._STOP, next(self._seq), None))       # after what waits


def _done(value: Any) -> "concurrent.futures.Future":
    """A future that already holds ``value``."""
    fut: "concurrent.futures.Future" = concurrent.futures.Future()
    fut.set_result(value)
    return fut


def _then(fut: "concurrent.futures.Future", fn: Callable[[Any], Any]) -> "concurrent.futures.Future":
    """A future of ``fn(result of fut)`` (each asker of one calculation gets their own answer of it)."""
    out: "concurrent.futures.Future" = concurrent.futures.Future()

    def done(f: "concurrent.futures.Future") -> None:
        try:
            out.set_result(fn(f.result()))
        except BaseException as exc:  # noqa: BLE001 - delivered to the asker
            out.set_exception(exc)

    fut.add_done_callback(done)
    return out


_DUMMY: List[str] = []
_NOT_SET = object()


def _flag(v: Any) -> bool:
    """A yes / no of a request: true, 1, "true", "1", "evet" - the text "false" is a no."""
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "evet", "yes", "on")
    return bool(v)


def _dummy_hash() -> str:
    """A hash to check a password against when the name does not exist (made once, on the first such sign-in)."""
    if not _DUMMY:
        _DUMMY.append(auth.hash_password(uuid.uuid4().hex))
    return _DUMMY[0]


#: the manual USDTRY spot of the workbook (VİOP sheet, "Manuel SP"): empty cells mean Bloomberg
MANUAL_SPOT = {"book": "tto", "bid": "VIOP!AA9", "ask": "VIOP!AA10", "status": "VIOP!AA8", "shown_as": "VIOP!$AA$8"}


class Service(object):
    def __init__(self, settings: Optional[Settings] = None, provider=None, store: Optional[Store] = None,
                 clock: Optional[Clock] = None):
        self.settings = settings or Settings()
        self._clock_override = clock
        from .ops import Ops, open_failed
        try:
            self.store = store or Store(self.settings.db_path)
        except sqlite3.DatabaseError as exc:          # a file that cannot even be opened: say where the backups are
            raise RuntimeError(open_failed(self.settings, exc)) from exc
        # operations: the log of what the loops survive, how fresh the market data is, the database's check and
        # nightly backup (ops.py)
        self.ops = Ops(self)
        self.ops.check_database()
        # the desk's alarms: set once, they ring for everyone; the system's own (deskalarms.py)
        from .deskalarms import DeskAlarms
        self.desk_alarms = DeskAlarms(self)
        self.et = EngineThread()
        # the generation: what the pages compare - it starts above any number a page could still hold from before
        # a restart (a page that sent "since" an old number would otherwise take everything for unchanged)
        self.gen = int(time.time() * 1000)
        # the changes at the desk that are no market move (a chat line, a trade, a setting, an input, a bond listed ...):
        # after one, a page kept for a user with inputs of their own is made again at once, never held back as a
        # market move is (_fresh)
        self.desk_changes = 0
        # Broker Chat's own changes (a line kept or removed, the board reset, its stale limit, the list of names): the live
        # stream carries the count - a box of the board asks again then, not with every generation of the market
        self.broker_changes = 0
        self._gen_lock = threading.Lock()
        self._notified = 0.0                             # when the pages were last told of a new generation
        self._notify_due = False                         # ... and whether they will be told once more
        self._auth_lock = threading.Lock()               # account changes one at a time (two first administrators ...)
        self._hash_slots = threading.BoundedSemaphore(auth.HASH_SLOTS)    # password checks at a time
        self._listeners: List[Callable[[int], None]] = []
        self._bbg_kept_at = 0.0                           # Bloomberg answers kept up to this time (_keep_bloomberg)
        self._seen: Dict[str, float] = {}                 # user -> when they last asked for anything (monotonic)
        self._streams: Dict[str, int] = {}               # user -> live-update streams open
        self._overlays: Dict[Tuple[str, str], Dict[Tuple[int, int], Any]] = {}
        self._retired: Dict[str, set] = {}
        # pages and headers kept per calculation (see view_future): key -> what was made, panel by panel
        self._renders: Dict[Tuple, Dict[str, Any]] = {}
        self._private_users: set = set()                 # users with inputs of their own (their pages are theirs)
        self._render_lock = threading.Lock()
        self._warming = False                            # a round of warming up is under way (warm)
        self.warmed = 0                                  # rounds done
        self._inflight: Dict[Tuple, "concurrent.futures.Future"] = {}     # pages / headers being made now
        # sessions looked up lately: token hash -> (user, role, until) - not a database query per request
        self._sessions: Dict[str, Tuple[str, Optional[str], float]] = {}
        self._sessions_lock = threading.Lock()
        # live: when the dashboard saw each security trade today (its last price changed or its volume grew)
        self._trades_day = ""
        self._trades_seen: Dict[str, Dict[str, Any]] = {}
        self._trade_last: Dict[Tuple[str, str], float] = {}
        self._stop = threading.Event()
        self._market_thread: Optional[threading.Thread] = None
        self.started_at = time.time()
        self.formulas = None                             # the inputs typed as formulas (inputformula.py), below
        self.et.call(self._setup, provider)
        from .history import History
        self.history = History(self)
        # the watch lists and the alarms: read again whenever the market or an input moved
        from .watch import Watch
        self.watch = Watch(self)
        # Spot / FX and FX vol: the option market's quotes of a pair, its smile and distribution, the vol monitor
        from .fx import Fx
        self.fx = Fx(self)
        # the desk's own corner: reports to the administrators, the chat (Sosyal), the agenda (Ajanda)
        from .desk import Desk
        self.desk = Desk(self)
        # quant signals (quant.py): statistics of the closes in a thread of their own, never on the engine thread
        from .quant import Quant
        self.quant = Quant(self)
        # each user's own calc sheets on the launchpads (calc.py): formulas over the workbooks' cells, never Bloomberg
        from .calc import CalcSheets
        self.calcsheets = CalcSheets(self)
        # inputs typed as formulas (=C60+7): evaluated by the calc sheets' machinery, again whenever what they read moved
        from .inputformula import InputFormulas
        formulas = InputFormulas(self)
        self.et.call(formulas.start)
        self.formulas = formulas
        self._watch_kick = threading.Event()
        self._watch_thread = threading.Thread(target=self._watch_loop, name="tto-watch", daemon=True)
        self._watch_thread.start()

    # ================================================================== setup
    def _setup(self, provider) -> None:
        s = self.settings
        self.mode = "replay"
        self.mode_note = ""
        if provider is None and s.mode in ("auto", "live"):
            try:
                provider = self._bloomberg()
                self.mode = "live"
            except Exception as exc:  # noqa: BLE001
                if s.mode == "live":
                    raise
                self.mode_note = "Bloomberg bağlantısı kurulamadı (%s) – kayıtlı veriyle çalışıyor" % (str(exc)[:160],)
                provider = None
        elif provider is not None and getattr(provider, "live", False):
            self.mode = "live"
        replay = self.mode != "live"
        if provider is None:
            provider = ReplayProvider(label="workbook")
        self.provider = provider
        clock = None
        if replay:
            from .xl.model import Model
            path = os.path.join(s.models_dir, "tto.json.gz")
            today = snapshot_today(Model.load(path)) if os.path.exists(path) else None
            if today is not None:
                clock = Clock(today + 0.5)
                clock.today = lambda: float(today)       # type: ignore[assignment]
        if self._clock_override is not None:
            clock = self._clock_override
        self.books: Dict[str, Book] = load_books(s.models_dir, provider=provider, clock=clock, replay=replay)
        if not self.books:
            raise ServiceError("model dosyaları bulunamadı: %s" % s.models_dir, 500)
        self.renderers = {bid: Renderer(b) for bid, b in self.books.items()}
        self.views = [v for v in load_views() if v["book"] in self.books]
        self.view_index = {v["id"]: v for v in self.views}
        self._shortcut_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._leftover_cache: Dict[str, Any] = {}
        self._snapshot_mark: Dict[str, int] = {}
        for v in self.views:
            book = self.books[v["book"]]
            for inp in v.get("inputs", []):
                try:
                    book.declare(inp["range"], v.get("sheet"), scope=inp.get("scope", "user"),
                                 group=inp.get("group"), kind=inp.get("kind", "auto"), label=inp.get("label", ""),
                                 options=inp.get("options"), view=v["id"], aliases=inp.get("aliases"))
                except (KeyError, ValueError):
                    continue
        tto = self.books.get("tto")
        if tto is not None:
            for ref in bl.input_ranges():
                tto.declare(ref, scope="shared", group="blotter", view="blotter")
            for ref in ("Forward!D2", "Forward!B163", "Forward!L163"):
                tto.declare(ref, scope="user", group="fwd-pricer", view="forward")
        asw = self.books.get("asw")
        if asw is not None and ex.FXC_SHEET in asw.model.sheet_index and "ASW" in asw.model.sheet_index:
            # the OIS quotes the ASW curve is built from are swapped for the FX swap curve in a calculation of its
            # own (ASW against FX swaps): the engine has to know what depends on them - not inputs of the page
            si = asw.model.sheet_index["ASW"]
            asw.engine.declare_inputs([(si, parse_a1("%s65" % index_to_col(3 + k))) for k in range(len(ex.FXC_ROOTS))],
                                      group="asw-fx-curve")
        if tto is not None:
            if ex.SRC_SHEET in tto.model.sheet_index:          # the order of the pricing sources (settings page)
                tto.declare("%s!B4:E6" % ex.SRC_SHEET, scope="shared", group="sources", kind="text",
                            label="Bloomberg fiyat kaynağı sırası (OIS / offshore / XCCY)", view="settings")
            if ex.HOL_SHEET in tto.model.sheet_index:          # the USD and EUR holiday lists (settings page)
                for ccy, (dcol, ncol) in ex.HOL_COLS.items():
                    for col, kind, group, label in ((dcol, "date", ccy.lower(), "%s tatilleri (FX valörleri)" % ccy),
                                                    (ncol, "text", ccy.lower() + "-names", "%s tatil adları" % ccy)):
                        tto.declare("%s!%s%d:%s%d" % (ex.HOL_SHEET, col, ex.HOL_FIRST, col, ex.HOL_LAST), scope="shared",
                                    group="holidays-" + group, kind=kind, label=label, view="settings")
        if replay:
            if isinstance(provider, ReplayProvider):
                if tto is not None:
                    provider.update(snapshot_from_model(tto.engine))
                # offline quotes for the workbooks that recorded none themselves (see tools/make_replay_quotes.py)
                folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
                for name in ("replay_usd.json", "replay_asw.json", "replay_borsa.json"):
                    if os.path.exists(os.path.join(folder, name)):
                        provider.load_quotes(os.path.join(folder, name))
                if os.path.exists(os.path.join(folder, "replay_history.json")):
                    provider.load_history(os.path.join(folder, "replay_history.json"))    # closes the file did not record
                for b in self.books.values():
                    b.engine.reset()
        # the steps per meeting and the VİOP target table start empty for everybody (extras.EMPTY_BY_DEFAULT): copies
        # of the file's old values kept as shared inputs (a calendar change carried them along) go - once
        # (only where they do start empty: a file that the addition does not fit keeps its steps, and their copies)
        tto = self.books.get("tto")
        if tto is not None and not any(x.startswith(ex.EMPTY_NAME + ":") for x in tto.left_out):
            if not self.store.get("migrated.empty_defaults"):
                self.store.clear_shared_inputs("tto", ex.empty_default_refs(ex.EMPTY_FIRST))
                self.store.put("migrated.empty_defaults", now_iso())
        for book in self.books.values():
            self._drop_file_copies(book)
        # Tüm Kâğıtlar: the desk's list of bonds (the bonds typed into the page's old own rows join it - once)
        self._desk_lock = threading.Lock()
        self._uni_rows: Dict[str, int] = {}
        self._uni_written: Dict[Tuple[int, int], Any] = {}
        self._uni_day: Optional[_dt.date] = None  # the day the rows were written for (past maturity: off the next day)
        self._uni_tried = time.time()            # the kinds Bloomberg has not told: asked again in BOND_RETRY
        self._migrate_own_bonds()
        bd.set_desk(self._desk_now(), owner=self)
        # shared inputs saved earlier (RET curve, calendars ...)
        for (bid, ref), val in self.store.shared_inputs().items():
            book = self.books.get(bid)
            if book is None:
                continue
            try:
                key = book.cell(ref)
            except (KeyError, ValueError):
                continue
            if key not in book.inputs:
                book.declare(ref, scope="shared", group="adhoc-shared")
            book.engine.set_inputs({key: _from_json(val)})
        self._declare_saved_cells()
        self._private_users = set(self.store.users_with_inputs())
        self._sync_universe()
        self._sync_blotter()                     # (may compute: a meeting-dated OIS of the day is priced)

    def _declare_saved_cells(self) -> None:
        """Every cell any user typed a value over ("Elle değer") or keeps in a saved scenario: declared now, in one go,
        before anything is computed - when that costs nothing.  Declared on the user's first request instead (or when
        a scenario was loaded), a constant among them made every value of every user computed again (~10 s for
        everybody, after every restart)."""
        cells: Dict[str, List[Tuple[int, int]]] = {}
        for bid, ref in self.store.saved_cells():
            book = self.books.get(bid)
            if book is None:
                continue
            try:
                cell = book.cell(ref)
            except (KeyError, ValueError):
                continue
            if cell in book.inputs or cell in self._retired_cells(book):
                continue                       # (a page's input already - shared ones included -, or one that moved)
            cells.setdefault(bid, []).append(cell)
        for bid, found in cells.items():
            self.books[bid].declare_cells(found, scope="user", group="adhoc")

    #: the cells whose stored shared copies of the file's value went already (``_drop_file_copies``): {book: [ref, ...]}
    FILE_COPIES_DONE = "migrated.file_copies"

    def _drop_file_copies(self, book: Book) -> None:
        """Input cells the dashboard's additions empty or give a formula default later on (the manual USDTRY spot ...):
        the file's value of the day it was saved is nobody's choice today.  A shared value stored of such a cell goes -
        once per cell, and only when it is the file's own value (a copy); a value the desk typed that differs stays.
        The additions note the file's values in the model (``extras.FILE_VALUES``); a cell of a file an addition does
        not fit is not noted, and so waits for a file it fits."""
        file_values = book.model.meta.get(ex.FILE_VALUES) or {}
        if not file_values:
            return
        done_all = self.store.get(self.FILE_COPIES_DONE) or {}
        done = set(done_all.get(book.id) or [])
        todo = [ref for ref in file_values if ref not in done]
        if not todo:
            return
        stored = self.store.shared_inputs(book.id)
        drop = [ref for ref in todo if (book.id, ref) in stored and _same_value(_from_json(stored[(book.id, ref)]), file_values[ref])]
        if drop:
            self.store.clear_shared_inputs(book.id, drop)
        done_all = dict(done_all)
        done_all[book.id] = sorted(done | set(todo))
        self.store.put(self.FILE_COPIES_DONE, done_all)

    def _bloomberg(self):
        """A started Bloomberg provider: its session in a helper process, or - when that is switched off or
        the helper does not come up - inside this process, with the reader thread favoured and ticks
        conflated.  Raises what the session raises (blpapi missing, terminal not reachable)."""
        s = self.settings
        from .marketdata.bloomberg import BloombergProvider, favour_reader
        common = dict(stream=s.bbg_stream, price_poll=s.bbg_price_poll, max_hits_per_day=s.bbg_max_hits, bfx=s.bbg_bfx,
                      queue_size=s.bbg_queue)
        stand_in = os.environ.get("TTO_BLPAPI_MODULE") or None      # tests: a module to use in place of blpapi
        if s.bbg_isolate:
            from .marketdata.bbg_process import IsolatedBloombergProvider, IsolationError
            try:
                provider = IsolatedBloombergProvider(s.bbg_host, s.bbg_port, interval=s.bbg_interval or 0.0,
                                                     blpapi_name=stand_in, silent_restart=s.bbg_silent_restart, **common)
                # a helper gone silent is started again in market hours only (each new one asks for everything)
                provider.restart_allowed = self.ops.in_market
                self._kept_bloomberg(provider)
                provider.start()
                return provider
            except IsolationError as exc:
                self.mode_note = "Bloomberg yardımcı süreci başlatılamadı (%s) – oturum dashboard'un kendi sürecinde" % (
                    str(exc)[:120],)
        module = None
        if stand_in:
            import importlib
            module = importlib.import_module(stand_in)
        provider = BloombergProvider(s.bbg_host, s.bbg_port, interval=1.0 if s.bbg_interval is None else s.bbg_interval,
                                     blpapi_module=module, **common)
        self._kept_bloomberg(provider)
        provider.start()
        favour_reader()
        return provider

    def _kept_bloomberg(self, provider) -> None:
        """What an earlier run of today used and was answered (kept in the database by :meth:`_keep_bloomberg`): the
        daily data limit counts it, and the reference answers are not asked again until they are due."""
        today = _dt.date.today().isoformat()
        self._bbg_kept_at = 0.0
        try:
            used = self.store.get("bbg.hits") or {}
            if isinstance(used, dict) and used.get("day") == today:
                provider.carry_hits(int(used.get("hits") or 0))
            provider.preload(self.store.bbg_answers(today))
        except Exception:  # noqa: BLE001 - a start from nothing, as before
            pass

    #: seconds between two keepings of the day's Bloomberg count and answers
    BBG_KEEP_EVERY = 30.0

    def _keep_bloomberg(self) -> None:
        """Keep the data points used today and the reference answers got since the last time (live: every
        ``BBG_KEEP_EVERY`` seconds and when the dashboard stops) - a restart the same day does not spend the daily
        data limit on them again."""
        prov = self.provider
        answers = getattr(prov, "answers", None)
        if answers is None:
            return
        today = _dt.date.today().isoformat()
        try:
            st = prov.status() or {}
            self.store.put("bbg.hits", {"day": today, "hits": int(st.get("hits_today") or 0)})
            got = answers(self._bbg_kept_at)
            if got:
                self.store.bbg_keep(today, got)
                self._bbg_kept_at = max(t for _, _, t in got)
        except Exception:  # noqa: BLE001 - kept the next time
            pass

    # ================================================================== lifecycle / events
    def start(self) -> None:
        if self._market_thread is None:
            self._market_thread = threading.Thread(target=self._market_loop, name="tto-market", daemon=True)
            self._market_thread.start()
            if self.mode == "live":
                threading.Thread(target=self._warmup_safe, name="tto-warmup", daemon=True).start()
            self.history.start()
            self.ops.start()
            self.quant.start()
            self.warm()
            threading.Thread(target=self._build_ref_indexes, name="tto-refs", daemon=True).start()

    # ------------------------------------------------------------------ warming up
    def warm(self) -> bool:
        """The header strip and every page made ahead for everybody without inputs of their own - at the calculation
        thread's lowest priority, one page at a time (a request in between goes first): the first trader of the
        morning does not wait for the workbook's first calculation.  After the start, the day's turn and a change of
        the meeting calendar.  False: a round is under way already."""
        with self._render_lock:
            if self._warming:
                return False
            self._warming = True
        self.et.submit_at(EngineThread.BACKGROUND, self._warm_step, 0)
        return True

    def _warm_step(self, i: int) -> None:
        try:
            if self._stop.is_set():
                return
            if i == 0:
                key = self._render_key(None, "#header", False, None)
                self._header_job(("warm",), key, None, None)
            else:
                vid = self.views[i - 1]["id"]
                if not self.views[i - 1].get("admin"):          # (an administrators' page is kept per administrator)
                    self._render_job(None, self._render_key(None, vid, False, None), None, vid, False, None, None)
        except Exception:  # noqa: BLE001 - warming up is an optimisation only
            pass
        if i < len(self.views) and not self._stop.is_set():
            self.et.submit_at(EngineThread.BACKGROUND, self._warm_step, i + 1)      # (after what waits now)
        else:
            with self._render_lock:
                self._warming = False
                self.warmed += 1

    #: seconds after the start before the reverse reference indexes are built (the first pages come first)
    REF_INDEX_DELAY = 45.0

    def _build_ref_indexes(self) -> None:
        """Which formulas read which cell (engine.ref_index, ~10 s, ~45 MB for the four workbooks): built ahead, in the
        background, so that the first constant typed over on a page does not wait for it (it is followed through the
        formulas that name it instead of every value of every user being computed again)."""
        if self._stop.wait(self.REF_INDEX_DELAY):
            return
        for book in list(self.books.values()):
            if self._stop.is_set():
                return
            try:
                book.engine.ref_index()
            except Exception:  # noqa: BLE001 - built when first needed instead
                continue

    def _warmup_safe(self) -> None:
        try:
            self.warmup()
        except Exception:  # noqa: BLE001 - warming up is an optimisation only
            pass

    def warmup(self, rounds: int = 30, timeout: float = 180.0) -> Dict[str, Any]:
        """Live mode: ask Bloomberg for everything the workbooks use before the first page is opened.

        Evaluating the add-in cells registers what is needed; when the answers arrive the cells that used
        them are recalculated, which may ask for more (tickers built from other answers ...).  Repeats until
        nothing is outstanding.
        """
        prov = self.provider
        busy = getattr(prov, "busy", None)
        drain = getattr(prov, "drain_changes", None)
        t0 = time.time()
        done = 0
        total = 0
        while done < rounds and time.time() - t0 < timeout and not self._stop.is_set():
            done += 1
            self.et.call(self._touch_addins)
            while busy is not None and busy() and time.time() - t0 < timeout and not self._stop.is_set():
                time.sleep(0.05)
            keys = drain() if drain else []
            if not keys:
                break
            total += len(keys)
            self.et.call_at(EngineThread.WRITE, self._apply_market, keys)
        self.bump()
        return {"rounds": done, "items": total, "seconds": round(time.time() - t0, 2)}

    def _touch_addins(self) -> int:
        from .xl.engine import addin_cells
        n = 0
        for b in self.books.values():
            calc = b.engine.shared
            for si, rc in addin_cells(b.model):
                r, c = divmod(rc, COLS)
                try:
                    calc.get(si, r, c)
                    n += 1
                except Exception:  # noqa: BLE001
                    continue
        return n

    def stop(self) -> None:
        self._stop.set()
        bd.drop_desk(self)
        self.history._stop.set()                   # no new work while the provider goes down
        self.history._kick.set()
        self.ops.stop()
        self.quant.stop()
        self.fx.stop()
        if self.mode == "live":
            self._keep_bloomberg()
        try:
            stop = getattr(self.provider, "stop", None)
            if stop:
                stop()
        finally:
            try:
                self.history.stop()
            finally:
                self.et.stop()

    #: how often the running dashboard looks whether a meeting has passed: the OIS spot (OIS_MAIN!B2) moves with the day
    #: and with the TRY holiday list, which may be edited at any time
    ROLL_CHECK_SECONDS = 600.0

    def _market_loop(self) -> None:
        last_day = None
        last_roll = 0.0
        kept = time.monotonic()
        busy = getattr(self.provider, "busy", None)
        while not self._stop.wait(0.3 if (busy is not None and busy()) else self.settings.tick_seconds):
            try:
                drain = getattr(self.provider, "drain_changes", None)
                keys = drain() if drain else []
                day = _dt.date.today()
                first = last_day is None
                day_changed = last_day is not None and day != last_day
                last_day = day
                if keys or day_changed or self.mode == "live":
                    changed = self.et.call_at(EngineThread.WRITE, self._apply_market, keys)
                    if changed or day_changed:
                        if day_changed:
                            self.et.call_at(EngineThread.WRITE, self._sync_blotter)
                        self.bump(market=not day_changed)          # (a new day: TODAY moved everything)
                    if day_changed:
                        self.warm()                      # a new day: TODAY moved everything
                if self.mode == "live" and time.monotonic() - kept >= self.BBG_KEEP_EVERY:
                    kept = time.monotonic()
                    self._keep_bloomberg()
                if first or day_changed or time.monotonic() - last_roll >= self.ROLL_CHECK_SECONDS:
                    # a meeting that passed leaves the list by itself: MPC1 is always the next meeting
                    last_roll = time.monotonic()
                    self.history.auto_roll()
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything (and say so in the log)
                self.ops.failure("piyasa döngüsü", exc)
                continue

    def _apply_market(self, keys) -> bool:
        changed = False
        self._note_trades(keys)
        for b in self.books.values():
            if keys and b.engine.market_changed(keys):
                changed = True
            before = b.engine.shared.evals
            b.engine.clock_tick()
        return changed or bool(keys)

    #: the real-time fields whose change tells that a security traded: its last price, its volume of the day
    TRADE_FIELDS = ("LAST_PRICE", "VOLUME")

    def _note_trades(self, keys) -> None:
        """The moment a security traded, as far as the dashboard saw it: its last price changed or its volume of
        the day grew (a trade at the same price as the one before still adds to the volume).  The first answer of
        the day is not a trade; a new day starts afresh."""
        get = getattr(self.provider, "get_bdp", None)
        if get is None or not keys:
            return
        now = _dt.datetime.now()
        day = now.date().isoformat()
        if day != self._trades_day:
            self._trades_day = day
            self._trades_seen.clear()
            self._trade_last.clear()
        for k in keys:
            if k[0] != "BDP" or len(k) < 4 or k[2] not in self.TRADE_FIELDS or k[3]:
                continue
            try:
                v = get(k)
            except Exception:  # noqa: BLE001 - a value that cannot be read is no trade
                continue
            if type(v) is not float:
                continue
            prev = self._trade_last.get((k[1], k[2]))
            self._trade_last[(k[1], k[2])] = v
            if prev is None or v == prev or (k[2] == "VOLUME" and v < prev):
                continue
            seen = self._trades_seen.setdefault(k[1], {})
            seen["time"] = now.strftime("%H:%M:%S")
            seen["by"] = k[2]
            if k[2] == "LAST_PRICE":
                seen["price"] = v
            else:
                seen["volume"] = v - prev                    # what this trade (or these trades) added

    def trades_seen(self, security: str) -> Optional[Dict[str, Any]]:
        """When the dashboard saw ``security`` trade today (``None``: not since it started, or not today)."""
        if self._trades_day != self.today_iso():
            return None
        return self._trades_seen.get(security)

    def _watch_loop(self) -> None:
        """Watch lists and alarms: read after every change (at the latest every few seconds), on the calculation
        thread; an alarm that fired tells the pages (a new generation: they ask what fired)."""
        pending: Optional["concurrent.futures.Future"] = None
        swept = time.monotonic()
        asked, late = 0.0, False
        while not self._stop.is_set():
            self._watch_kick.wait(3.0)
            self._watch_kick.clear()
            if self._stop.is_set():
                break
            if time.monotonic() - swept >= 60.0:
                swept = time.monotonic()
                self.et.submit_at(EngineThread.BACKGROUND, self._sweep_idle)      # (users gone for a while)
            try:
                if self._uni_day != self._bond_day() and self.et.submit(self._sync_universe).result(timeout=60):
                    self.bump()                    # a new day: the bonds past their maturity leave Tüm Kâğıtlar
                if bd.pending() and time.time() - self._uni_tried >= self.BOND_RETRY:
                    self._classify_pending()
            except Exception:  # noqa: BLE001
                pass
            if pending is not None and not pending.done():
                if not late and time.monotonic() - asked >= 60.0:
                    late = True                 # (said once a round)
                    self.ops.failure("izleme / alarm döngüsü", RuntimeError(
                        "tur 60 sn'de bitmedi – hesap motoru meşgul (%d iş bekliyor)" % self.et.queued()))
                continue                    # the last round still waits behind the pages: no second one queued
            pending, asked, late = self.et.submit_at(EngineThread.BACKGROUND, self.watch.tick), time.monotonic(), False
            pending.add_done_callback(self._watch_done)

    def _watch_done(self, fut: "concurrent.futures.Future") -> None:
        try:
            fired = fut.result()
        except BaseException as exc:  # noqa: BLE001 - the loop must survive anything (and a calculation thread gone)
            if isinstance(exc, Exception):
                self.ops.failure("izleme / alarm döngüsü", exc)
            return
        if fired:
            self.bump()

    #: the pages are told of a new generation at most this often (seconds): a busy market bumps every 0.3 s, and
    #: every page asks again each time it is told
    NOTIFY_EVERY = 1.0

    def bump(self, market: bool = False) -> int:
        kick = getattr(self, "_watch_kick", None)
        if kick is not None:
            kick.set()
        fx = self.formulas
        if fx is not None and fx.active:
            fx.schedule()                         # (the inputs typed as formulas follow what they read: ahead of the pages)
        with self._gen_lock:
            self.gen += 1
            if not market:
                self.desk_changes += 1
            g = self.gen
            now = time.monotonic()
            wait = self._notified + self.NOTIFY_EVERY - now
            if wait > 0:
                # told less than a second ago: told once more when the second is over (of the generation then)
                if not self._notify_due:
                    self._notify_due = True
                    t = threading.Timer(wait, self._notify_late)
                    t.daemon = True
                    t.start()
                return g
            self._notified = now
            listeners = list(self._listeners)
        self._tell(listeners, g)
        return g

    def _notify_late(self) -> None:
        with self._gen_lock:
            self._notify_due = False
            self._notified = time.monotonic()
            g = self.gen
            listeners = list(self._listeners)
        self._tell(listeners, g)

    def nudge(self) -> None:
        """Tell the open pages that something of the desk's own corner changed (a chat message, a report, the agenda):
        no new generation - their tables are not read again; the live stream carries the corner's counters."""
        with self._gen_lock:
            g = self.gen
            listeners = list(self._listeners)
        self._tell(listeners, g)

    @staticmethod
    def _tell(listeners: List[Callable[[int], None]], gen: int) -> None:
        for fn in listeners:
            try:
                fn(gen)
            except Exception:  # noqa: BLE001
                pass

    def add_listener(self, fn: Callable[[int], None]) -> None:
        with self._gen_lock:
            self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[int], None]) -> None:
        with self._gen_lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    # ================================================================== users & overlays
    def login(self, name: str) -> Dict[str, Any]:
        """The user of a name, made (active, without a password) when new - the program's and the tests' own way to
        a user key.  It signs nobody in: over HTTP a user signs in with a password (``authenticate``)."""
        try:
            return self.store.login(name)
        except ValueError as exc:
            raise ServiceError(str(exc))

    def require_user(self, user: Optional[str]) -> str:
        if not user:
            raise ServiceError("önce giriş yapın", 401)
        key = user_key(user)
        acc = self.store.account(key)
        if acc is None:
            raise ServiceError("kullanıcı bulunamadı – tekrar giriş yapın", 401)
        if acc.get("status") != "active":
            raise ServiceError("hesap etkin değil – tekrar giriş yapın", 401)
        self.saw(key)
        return key

    def require_admin(self, user: Optional[str]) -> str:
        key = self.require_user(user)
        if (self.store.account(key) or {}).get("role") != "admin":
            raise ServiceError("bu işlem yalnızca yöneticiler içindir", 403)
        return key

    # ================================================================== sign-in and accounts
    @staticmethod
    def _now() -> _dt.datetime:
        return _dt.datetime.now()

    @staticmethod
    def _account_name(name: Any) -> str:
        try:
            display = auth.clean_name(name)
        except ValueError as exc:
            raise ServiceError(str(exc))
        if not display:
            raise ServiceError("isim boş olamaz")
        if len(display) > 40:
            raise ServiceError("isim en fazla 40 karakter olabilir")
        return display

    def _slot(self) -> None:
        """A free place among the password checks (``auth.HASH_SLOTS`` at a time, ~0.5 s each): a flood of sign-ins
        is turned away after ``auth.HASH_WAIT`` seconds instead of taking every thread of the server."""
        if not self._hash_slots.acquire(timeout=auth.HASH_WAIT):
            raise ServiceError("sunucu şu an çok sayıda giriş denemesini işliyor – biraz sonra tekrar deneyin", 429)

    def _check(self, password: Any, stored: Optional[str]) -> bool:
        self._slot()
        try:
            return auth.check_password(str(password or ""), stored)
        finally:
            self._hash_slots.release()

    def _new_password(self, password: Any) -> str:
        problem = auth.password_problem(password)
        if problem:
            raise ServiceError(problem)
        self._slot()
        try:
            return auth.hash_password(str(password))
        finally:
            self._hash_slots.release()

    def _verify(self, key: str, acc: Dict[str, Any], password: Any) -> bool:
        """The password of an account, with its lock: the attempt is counted before the slow check, in one step
        with the look at the lock (guesses sent at once each take their own turn); the ``auth.MAX_FAILED``-th wrong
        one in a row locks the name for ``auth.LOCK_SECONDS``."""
        now = self._now()
        tries, locked = self.store.count_attempt(key, auth.stamp(now))
        if locked or tries > auth.MAX_FAILED:
            until = locked or self._lock_name(key, now)
            raise ServiceError("çok fazla hatalı deneme – %s'den sonra tekrar deneyin" % until[11:19], 429)
        if self._check(password, acc.get("pw_hash")):
            return True
        if tries >= auth.MAX_FAILED:
            self._lock_name(key, now)
        return False

    def _lock_name(self, key: str, now: _dt.datetime) -> str:
        until = auth.stamp(now + _dt.timedelta(seconds=auth.LOCK_SECONDS))
        self.store.update_account(key, failed=0, locked_until=until)
        return until

    def me(self, user: str) -> Dict[str, Any]:
        """The signed-in user as the page needs it (an administrator also learns how many requests wait)."""
        acc = self.store.account(user_key(user)) or {}
        out = {"user": acc.get("name"), "display": acc.get("display"), "role": acc.get("role") or "user"}
        if out["role"] == "admin":
            out["pending"] = self.store.pending_count()
        return out

    def auth_state(self, user: Optional[str], local: bool) -> Dict[str, Any]:
        """Before the page shows anything: who is signed in (``None``: nobody), whether the dashboard still has no
        administrator (``setup``: the first one is created from this computer only) and whether the request came
        from this computer."""
        return {"user": self.me(user) if user else None, "setup": not self.store.admins(), "local": bool(local)}

    def session_user(self, token: Optional[str]) -> Optional[str]:
        """The user of a session token that is still valid (``None`` otherwise)."""
        if not token:
            return None
        return self.store.session_user(auth.token_hash(token), auth.stamp(self._now()))

    #: how long a session looked up is taken as it was (a signed-out / ended one is forgotten at once by this process)
    SESSION_TTL = 60.0

    def cached_session(self, token: Optional[str]) -> Optional[Tuple[str, Optional[str]]]:
        """``(user, role)`` of a session looked up less than ``SESSION_TTL`` ago (``None``: look it up - in a thread:
        :meth:`resolve_session` queries the database).  Every request asks: no database query on the event loop."""
        if not token:
            return None
        h = auth.token_hash(token)
        with self._sessions_lock:
            hit = self._sessions.get(h)
        if hit is None or hit[2] < time.monotonic():
            return None
        return hit[0], hit[1]

    def resolve_session(self, token: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """``(user, role)`` of a session token (``(None, None)``: not valid), kept for ``SESSION_TTL`` seconds."""
        if not token:
            return None, None
        h = auth.token_hash(token)
        user = self.store.session_user(h, auth.stamp(self._now()))
        if user is None:
            return None, None
        role = (self.store.account(user) or {}).get("role")
        with self._sessions_lock:
            if len(self._sessions) > 5000:
                self._sessions.clear()
            self._sessions[h] = (user, role, time.monotonic() + self.SESSION_TTL)
        return user, role

    def forget_sessions(self, token: Optional[str] = None) -> None:
        """Sessions ended or changed (signed out, a new password, an account closed, a role changed): looked up again."""
        with self._sessions_lock:
            if token:
                self._sessions.pop(auth.token_hash(token), None)
            else:
                self._sessions.clear()

    def open_session(self, user: str, ip: Optional[str] = None) -> str:
        """A new session of an active user - after a correct password or the first administrator's set-up.  The token
        goes to the browser; the database keeps only its hash."""
        now = self._now()
        token = auth.new_token()
        self.store.purge_sessions(auth.stamp(now))
        self.store.add_session(auth.token_hash(token), user_key(user),
                               auth.stamp(now + _dt.timedelta(days=auth.SESSION_DAYS)), ip)
        return token

    def authenticate(self, name: Any, password: Any, ip: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """Sign in with a name and a password: ``(session token, me)``.  Wrong passwords in a row lock the name for
        a minute; an account waiting for approval or closed does not sign in."""
        try:
            display = auth.clean_name(name)
        except ValueError:
            display = ""
        key = user_key(display) if display else ""
        acc = self.store.account(key) if key else None
        wrong = ServiceError("isim ya da şifre hatalı", 401)
        if acc is None:
            self._check(password, _dummy_hash())                # as slow as a real check: no telling which names exist
            raise wrong
        if acc.get("pw_hash") is None:
            raise ServiceError("bu hesabın şifresi yok: \"Hesap iste\" ile aynı isimle şifrenizi belirleyin, bir yönetici "
                               "onaylayınca girebilirsiniz", 401)
        if not self._verify(key, acc, password):
            raise wrong
        if acc.get("status") == "pending":
            raise ServiceError("hesabınız bir yöneticinin onayını bekliyor", 403)
        if acc.get("status") != "active":
            raise ServiceError("hesabınız kapatılmış – bir yöneticiye başvurun", 403)
        self.store.update_account(key, failed=0, locked_until=None, last_seen=now_iso())
        return self.open_session(key, ip), self.me(key)

    def logout(self, token: Optional[str]) -> Dict[str, Any]:
        if token:
            self.store.drop_session(auth.token_hash(token))
            self.forget_sessions(token)
        return {"ok": True}

    def request_account(self, name: Any, password: Any, note: Any = "") -> Dict[str, Any]:
        """Ask for an account: it waits for an administrator.  A user of the earlier version (signed in by name only,
        no password) asks under the same name: the request sets the password of that account, and once approved
        its personal inputs and scenarios are still there."""
        display = self._account_name(name)
        full = ServiceError("çok sayıda istek onay bekliyor – bir yöneticiye başvurun", 429)
        if self.store.pending_count() >= auth.MAX_PENDING:
            raise full
        pw_hash = self._new_password(password)
        note = " ".join(str(note or "").split())[:200] or None
        key = user_key(display)
        with self._auth_lock:
            acc = self.store.account(key)
            if self.store.pending_count() >= auth.MAX_PENDING:
                raise full
            if acc is None:
                self.store.create_account(display, pw_hash, role="user", status="pending", note=note)
            elif acc.get("status") == "pending":
                raise ServiceError("bu isimle bir istek zaten onay bekliyor")
            elif acc.get("pw_hash") is None and acc.get("status") == "active":
                # the account becomes the requester's once approved - as a user: the role is an administrator's to
                # give, and only to an account with a password
                self.store.update_account(key, pw_hash=pw_hash, role="user", status="pending", note=note,
                                          requested_at=now_iso(), decided_by=None, decided_at=None, failed=0,
                                          locked_until=None)
                display = acc.get("display") or display
            else:
                raise ServiceError("bu isimde bir hesap var – şifrenizi unuttuysanız bir yöneticiye başvurun")
        return {"status": "pending", "display": display}

    def setup_admin(self, name: Any, password: Any, local: bool, ip: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """The first administrator, while there is none - from the dashboard's own computer only (nobody else on the
        network can take the role first)."""
        if not local:
            raise ServiceError("ilk yönetici yalnızca dashboard'un çalıştığı bilgisayardan oluşturulabilir", 403)
        display = self._account_name(name)
        pw_hash = self._new_password(password)
        key = user_key(display)
        with self._auth_lock:
            if self.store.admins():
                raise ServiceError("bir yönetici zaten var – giriş yapın", 409)
            if self.store.account(key) is None:
                self.store.create_account(display, pw_hash, role="admin", status="active", by=key)
            else:
                self.store.update_account(key, display=display, pw_hash=pw_hash, role="admin", status="active", failed=0,
                                          locked_until=None, decided_by=key, decided_at=now_iso())
        return self.open_session(key, ip), self.me(key)

    def change_password(self, user: Optional[str], old: Any, new: Any, token: Optional[str] = None) -> Dict[str, Any]:
        """One's own new password.  The other sessions of the account end (a password someone else learned signs in
        nowhere any more), the page that asked (``token``) stays; a wrong old password counts like a sign-in."""
        key = self.require_user(user)
        problem = auth.password_problem(new)
        if problem:
            raise ServiceError(problem)
        acc = self.store.account(key) or {}
        if not self._verify(key, acc, old):
            raise ServiceError("mevcut şifre hatalı", 403)
        self.store.update_account(key, pw_hash=self._new_password(new), failed=0, locked_until=None)
        self.store.drop_sessions(key, keep=auth.token_hash(token) if token else None)
        self.forget_sessions()
        return {"ok": True}

    # ------------------------------------------------------------------ the administrators' page
    def accounts(self, user: Optional[str]) -> Dict[str, Any]:
        self.require_admin(user)
        return {"accounts": self.store.accounts(), "pending": self.store.pending_count(), "admins": len(self.store.admins())}

    def admin_action(self, user: Optional[str], action: str, data: Dict[str, Any],
                     token: Optional[str] = None) -> Dict[str, Any]:
        """What an administrator does to an account: ``create`` (name, password, admin), ``approve`` / ``reject`` a
        request, ``role`` (admin: true / false), ``password`` (a new one), ``status`` (active: true / false).
        ``token``: the asking page's session (one's own new password keeps it).  ``demoted``: the administrator took
        the role from themself."""
        self.require_admin(user)
        fn = {"create": self._admin_create, "approve": self._admin_approve, "reject": self._admin_reject,
              "role": self._admin_role, "password": self._admin_password, "status": self._admin_status}.get(action)
        if fn is None:
            raise ServiceError("bilinmeyen işlem: %s" % action, 404)
        with self._auth_lock:
            me = self.require_admin(user)                  # again inside: one demoted meanwhile does nothing more
            try:
                if action == "password":
                    self._admin_password(me, data or {}, token)
                else:
                    fn(me, data or {})
            finally:
                self.forget_sessions()                     # (a session ended, a role changed ...)
        if (self.store.account(me) or {}).get("role") != "admin":
            return {"accounts": [], "pending": 0, "admins": len(self.store.admins()), "demoted": True}
        return self.accounts(user)

    def _target(self, data: Dict[str, Any]) -> Dict[str, Any]:
        key = user_key(str(data.get("name") or ""))
        acc = self.store.account(key) if key else None
        if acc is None:
            raise ServiceError("kullanıcı bulunamadı: %s" % (data.get("name") or ""), 404)
        return acc

    def _last_admin(self, acc: Dict[str, Any]) -> bool:
        return self.store.admins() == [acc["name"]]

    def _admin_create(self, me: str, data: Dict[str, Any]) -> None:
        display = self._account_name(data.get("name"))
        pw_hash = self._new_password(data.get("password"))
        role = "admin" if _flag(data.get("admin")) else "user"
        key = user_key(display)
        acc = self.store.account(key)
        if acc is None:
            self.store.create_account(display, pw_hash, role=role, status="active", by=me)
        elif acc.get("pw_hash") is None and acc.get("status") in ("active", "pending"):
            # a user of the earlier version: the account gets its password, its inputs and scenarios stay
            self.store.update_account(key, pw_hash=pw_hash, role=role, status="active", decided_by=me, decided_at=now_iso())
        else:
            raise ServiceError("bu isimde bir hesap var")

    def _admin_approve(self, me: str, data: Dict[str, Any]) -> None:
        acc = self._target(data)
        if acc.get("status") != "pending":
            raise ServiceError("onay bekleyen bir istek değil")
        self.store.update_account(acc["name"], status="active", decided_by=me, decided_at=now_iso())

    def _admin_reject(self, me: str, data: Dict[str, Any]) -> None:
        acc = self._target(data)
        if acc.get("status") != "pending":
            raise ServiceError("onay bekleyen bir istek değil")
        if acc.get("requested_new"):
            self.store.delete_account(acc["name"])            # a new name: the request was all there was of it
        else:
            # the request of an existing user (of the earlier version): the account stays as it was, without a password
            self.store.update_account(acc["name"], pw_hash=None, status="active", note=None, requested_at=None,
                                      decided_by=me, decided_at=now_iso())

    def _admin_role(self, me: str, data: Dict[str, Any]) -> None:
        acc = self._target(data)
        admin = _flag(data.get("admin"))
        if admin and acc.get("pw_hash") is None:
            # whoever asks for that name next would get the role with their own password
            raise ServiceError("şifresi olmayan hesap yönetici yapılamaz – önce şifre belirleyin")
        if not admin and acc.get("role") == "admin" and self._last_admin(acc):
            raise ServiceError("son yöneticinin yetkisi alınamaz – önce başka birini yönetici yapın")
        self.store.update_account(acc["name"], role="admin" if admin else "user")
        if self.formulas is not None:
            self.formulas.role_changed(acc["name"])   # (their inputs' formulas read with the role they have now)

    def _admin_password(self, me: str, data: Dict[str, Any], token: Optional[str] = None) -> None:
        acc = self._target(data)
        self.store.update_account(acc["name"], pw_hash=self._new_password(data.get("password")), failed=0, locked_until=None)
        # signed in elsewhere with the old password: out - one's own page that asked stays
        keep = auth.token_hash(token) if (token and acc["name"] == me) else None
        self.store.drop_sessions(acc["name"], keep=keep)

    def _admin_status(self, me: str, data: Dict[str, Any]) -> None:
        acc = self._target(data)
        if acc.get("status") == "pending":
            raise ServiceError("onay bekleyen istek: onaylayın ya da reddedin")
        if _flag(data.get("active")):
            self.store.update_account(acc["name"], status="active", failed=0, locked_until=None)
            return
        if acc["name"] == me:
            raise ServiceError("kendi hesabınızı kapatamazsınız")
        if acc.get("role") == "admin" and self._last_admin(acc):
            raise ServiceError("son yöneticinin hesabı kapatılamaz")
        self.store.update_account(acc["name"], status="disabled", decided_by=me, decided_at=now_iso())
        self.store.drop_sessions(acc["name"])

    # ------------------------------------------------------------------ the daily backup (the administrators' page)
    def backup_settings(self, user: Optional[str]) -> Dict[str, Any]:
        """When and where the database's daily backup goes (Araçlar → Yedekleme, administrators only): the settings as
        they stand, where each comes from, the newest backups of each folder (ops.Ops.backup_page)."""
        self.require_admin(user)
        return self.ops.backup_page()

    def set_backup_settings(self, user: Optional[str], values: Any = None, reset: bool = False) -> Dict[str, Any]:
        """The administrators' choice of the backup (``time``, ``dir``, ``copy_dir``; empty ``copy_dir``: no second
        copy), or back to the command line / defaults (``reset``).  A folder that cannot be taken is refused with the
        reason of each field (``errors``); it applies without a restart."""
        from .ops import BackupError
        me = self.require_admin(user)
        if reset:
            self.ops.reset_backup(me)
        else:
            try:
                self.ops.set_backup(values if isinstance(values, dict) else {}, me)
            except BackupError as exc:
                raise ServiceError(str(exc), 400, {"errors": exc.errors})
        self.bump()                                        # (the alarms page says the backup's time)
        return self.ops.backup_page()

    def backup_run(self, user: Optional[str]) -> Dict[str, Any]:
        """"Şimdi yedek al": a backup with the settings as they stand (administrators) - the file, its size, whether
        the second copy was written - and the page again."""
        me = self.require_admin(user)
        try:
            res = self.ops.backup_now(by=me)
        except Exception as exc:  # noqa: BLE001 - said in the log, kept for the status and the alarm
            raise ServiceError("Yedek alınamadı: %s: %s" % (type(exc).__name__, exc), 500)
        self.bump()
        return dict(self.ops.backup_page(), result=res)

    def _overlay(self, user: str, book: Book) -> Dict[Tuple[int, int], Any]:
        key = (user, book.id)
        ov = self._overlays.get(key)
        if ov is None:
            ov = {}
            fresh = []
            retired = self._retired_cells(book)
            dropped = []
            for (bid, ref), val in self.store.user_inputs(user, book.id).items():
                try:
                    cell = book.cell(ref)
                except (KeyError, ValueError):
                    continue
                if cell in retired:
                    dropped.append(ref)                # an input that moved: its old value is no one's input now
                    continue
                d = book.inputs.get(cell)
                if d is not None and d.scope == "shared":
                    # an input that became the desk's (VİOP contracts): a value one user kept of it would hide the
                    # desk's from them - every user sees what anyone sets there
                    dropped.append(ref)
                    continue
                if cell not in book.inputs:
                    fresh.append(ref)
                ov[cell] = _from_json(val)
            if dropped:
                self.store.clear_user_inputs(user, book.id, dropped)
                self._note_private(user)
            for ref in fresh:
                book.declare(ref, scope="user", group="adhoc")
            self._overlays[key] = ov
            if ov:
                book.engine.set_user_inputs(user, ov)
            fx = self.formulas
            if fx is not None and fx.has(user):
                fx.pending.add(user)              # (their inputs' formulas: worked out again before anything is read)
        return ov

    def _retired_cells(self, book: Book) -> set:
        """Cells of input cells that moved to another address in a later layout (``extras.RETIRED_INPUTS``)."""
        out = self._retired.get(book.id)
        if out is None:
            out = set()
            for ref in ex.RETIRED_INPUTS.get(book.id, ()):
                try:
                    out.update(book.cells_of(ref))
                except (KeyError, ValueError):
                    continue
            self._retired[book.id] = out
        return out

    def _calc(self, user: Optional[str], book: Book) -> Calc:
        if not user:
            return book.engine.shared
        ov = self._overlay(user, book)
        fx = self.formulas
        if fx is not None and fx.pending and user in fx.pending:
            fx.catch_up(user)                    # (back: their inputs' formulas evaluated over what is there now)
            ov = self._overlays.get((user, book.id), ov)
        if not ov:
            return book.engine.shared
        if user not in book.engine.users:
            return book.engine.set_user_inputs(user, ov)     # (given back while the user was away: made again)
        return book.engine.user(user)

    # ------------------------------------------------------------------ who is here
    #: a user seen this recently (seconds) - or with a live-update stream open - is connected
    CONNECTED_WINDOW = 120.0

    def saw(self, user: Optional[str]) -> None:
        """A request of the user (the session gate tells every one)."""
        if user:
            self._seen[user] = time.monotonic()

    def stream(self, user: Optional[str], delta: int) -> None:
        """A live-update stream of the user opened (+1) or closed (-1)."""
        if not user:
            return
        with self._gen_lock:
            n = self._streams.get(user, 0) + delta
            if n > 0:
                self._streams[user] = n
            else:
                self._streams.pop(user, None)
        self.saw(user)

    def connected(self, user: Optional[str]) -> bool:
        """Whether the user has the dashboard open: a stream, or a request lately."""
        if not user:
            return False
        if self._streams.get(user):
            return True
        return time.monotonic() - self._seen.get(user, -1e9) < self.CONNECTED_WINDOW

    def _sweep_idle(self) -> List[str]:
        """Users not seen for ``settings.idle_minutes``: their calculations (and kept pages) are given back - a user
        with inputs of their own holds a private copy of every value they changed (~50 000 for the OIS scenario
        inputs).  They are made again when the user returns.  Calculation thread."""
        limit = self.settings.idle_minutes * 60.0
        if limit <= 0:
            return []
        now = time.monotonic()
        gone = []
        names = {name for book in self.books.values() for name in book.engine.users}
        for name in names:
            if self._streams.get(name) or now - self._seen.get(name, -1e9) < limit:
                continue
            for book in self.books.values():
                book.engine.drop_user(name)
                self._overlays.pop((name, book.id), None)
            self._forget_renders(name)
            gone.append(name)
        return gone

    # ================================================================== status / navigation
    def describe(self) -> str:
        """One line for the console: where the market data comes from."""
        note = (" · " + self.mode_note) if self.mode_note else ""
        if self.mode != "live":
            return "Veri: kayıtlı (Excel dosyasındaki son piyasa verisi)" + note
        try:
            isolated = bool(self.provider.status().get("isolated"))
        except Exception:  # noqa: BLE001
            isolated = False
        where = "ayrı bir yardımcı süreçte" if isolated else "dashboard'un kendi sürecinde"
        return "Veri: Bloomberg canlı · oturum %s%s" % (where, note)

    def status(self) -> Dict[str, Any]:
        prov = {}
        try:
            prov = self.provider.status()
        except Exception:  # noqa: BLE001
            pass
        tto = self.books.get("tto")
        today = None
        if tto is not None:
            today = serial_to_date(tto.engine.clock.today()).isoformat()
        ret = self.ret_meta() if tto is not None else None
        return {"mode": self.mode, "note": self.mode_note, "provider": prov, "gen": self.gen, "today": today,
                "ret": ret, "server_date": _dt.date.today().isoformat(),
                # today's trades of the desk said in the broker chat and not entered in Günlük İşlemler (the menu's badge)
                "chat_missing": self.chat_unbooked(),
                "books": {bid: {"title": b.title, "formulas": b.model.formula_count(),
                                "source": b.model.meta.get("source"), "left_out": list(getattr(b, "left_out", []))}
                          for bid, b in self.books.items()},
                "port": self.settings.port,
                "streams": len(self._listeners),            # live-update streams open (one per browser)
                # how fresh the data is, the calculation thread's queue, the last fault a loop survived (ops.py)
                "ops": self.ops.status(prov)}

    def status_for(self, user: Optional[str]) -> Dict[str, Any]:
        """:meth:`status` as a signed-in user gets it over HTTP: where the log, the database and its backups live on
        the desk's computer - the folders the administrators chose too - is the administrators' to know (a database
        problem and a backup's date stay for all)."""
        from .ops import hide_paths
        out = self.status()
        try:
            self.require_admin(user)
            return out
        except ServiceError:
            pass
        hide = self.ops.private_paths()

        def clean(x: Any) -> Any:
            if isinstance(x, dict):
                return {k: clean(v) for k, v in x.items() if k not in ("path", "dir", "log")}
            if isinstance(x, list):
                return [clean(v) for v in x]
            if isinstance(x, str):
                return hide_paths(x, hide)
            return x

        out["ops"] = clean(out["ops"])
        return out

    def _is_admin(self, user: Optional[str]) -> bool:
        return bool(user) and (self.store.account(user_key(user)) or {}).get("role") == "admin"

    def _hidden_pages(self, user: Optional[str]) -> set:
        """The pages a user does not get (administrators' pages for everybody else).  ``None``: the service itself."""
        if user is None or self._is_admin(user):
            return set()
        return {v["id"] for v in self.views if v.get("admin")}

    def nav(self, user: Optional[str] = None) -> List[Dict[str, Any]]:
        """The pages of the menu (and of the search box) - an administrators' page only for them."""
        hidden = self._hidden_pages(user)
        pages = []
        for v in self.views:
            if v["id"] in hidden:
                continue
            # the tables of the page (as the page definition names them): what the search box of the top bar finds
            tab = {}
            for sec in v.get("sections", []):
                for pid in sec.get("panels", []):
                    tab.setdefault(pid, sec["title"])
            tables = [{"id": p["id"], "title": p.get("title") or "", "tab": tab.get(p["id"], "")}
                      for p in v["panels"] if not p.get("hidden") and p.get("title")]
            pages.append({"id": v["id"], "title": v["title"], "group": v.get("group", ""), "book": v["book"],
                          "sheet": v.get("sheet"), "tables": tables})
        if "tto" in self.books:
            pages.append({"id": "watch", "title": "İzleme · Alarmlar", "group": "Masa", "book": "tto", "sheet": None,
                          "custom": True})
            pages.append({"id": "heat", "title": "Eğri Hareketi", "group": "Masa", "book": "tto", "sheet": None, "custom": True})
            pages.append({"id": "blotter", "title": "Günlük İşlemler", "group": "Masa", "book": "tto",
                          "sheet": bl.SHEET, "custom": True})
            pages.append({"id": "broker", "title": "Broker Chat", "group": "Masa", "book": "tto", "sheet": None, "custom": True})
            # pages of the dashboard's own: what happened over time, and the settings behind it
            pages.append({"id": "eod", "title": "Gün Sonu Matrisi", "group": "Masa", "book": "tto", "sheet": None, "custom": True})
            pages.append({"id": "mpc", "title": "PPK Fiyatlama Geçmişi", "group": "TRY Faiz", "book": "tto", "sheet": None,
                          "custom": True})
            pages.append({"id": "vol", "title": "Realized Vol · Carry", "group": "TRY Faiz", "book": "tto", "sheet": None,
                          "custom": True})
            pages.append({"id": "spreads", "title": "Spread Geçmişi", "group": "TRY Faiz", "book": "tto", "sheet": None,
                          "custom": True})
            pages.append({"id": "settings", "title": "Ayarlar · Toplantı takvimi", "group": "Araçlar", "book": "tto",
                          "sheet": None, "custom": True})
            # the option market of the currency pairs: one pair in depth, and every pair's vols at a glance
            pages.append({"id": "fx", "title": "Spot / FX", "group": "FX", "book": "tto", "sheet": None, "custom": True})
            pages.append({"id": "fxvol", "title": "FX Vol İzleme", "group": "FX", "book": "tto", "sheet": None, "custom": True})
            # the quant signals and the analyses behind them (quant.py)
            pages.extend(self.quant.pages())
        # the desk's own corner (desk.py): the traders' chat and the agenda - pages of the desk, apart from any workbook
        pages.append({"id": "social", "title": "Sosyal", "group": "Masa", "book": None, "sheet": None, "custom": True})
        pages.append({"id": "agenda", "title": "Ajanda", "group": "Masa", "book": None, "sheet": None, "custom": True})
        return pages

    # ================================================================== rendering
    #: pages / headers kept (per calculation: everybody without inputs of their own shares one)
    RENDERS_KEPT = 120

    def view(self, user: Optional[str], view_id: str, show_hidden: bool = False, locale: Optional[str] = None,
             since: Optional[int] = None, panels: Optional[List[str]] = None, as_: Optional[str] = None) -> Dict[str, Any]:
        if self.et.here():
            key = self._render_key(user, view_id, show_hidden, locale)
            return self._answer(self._render_job(None, key, user, view_id, show_hidden, locale, None), since, None, as_)
        return self.view_future(user, view_id, show_hidden, locale, since, panels, None, as_).result()

    def view_future(self, user: Optional[str], view_id: str, show_hidden: bool = False, locale: Optional[str] = None,
                    since: Optional[int] = None, panels: Optional[List[str]] = None,
                    role: Optional[str] = None, as_: Optional[str] = None) -> "concurrent.futures.Future":
        """A page, as a future (the web layer awaits it without holding a thread of its own while the calculation
        thread is busy).

        Pages are kept per calculation: everybody without inputs of their own (and not an administrator - whose
        pages hint at the sheet explorer) shares one.  A generation later only the panels whose cells changed are
        made again (the masks of what a panel read meet what was invalidated since); the same page asked again while
        it is being made - two tabs, a refresh on the heels of another - waits for the one calculation.

        ``panels``: only these (the open tab's); ``since``: the generation the browser has them from - the panels that
        did not change since are left out (``{"unchanged": true}`` when none did).  ``as_``: which page the browser has
        them of (``"s"``: the one everybody shares, ``"p"``: the user's own - an answer says ``as``); ``since`` counts
        only on the same one."""
        v = self.view_index.get(view_id)
        if v is not None and v.get("admin") and user is not None and not (role == "admin" if role is not None else self._is_admin(user)):
            fut: "concurrent.futures.Future" = concurrent.futures.Future()
            fut.set_exception(ServiceError("bu sayfa yalnızca yöneticilere açıktır", 403))
            return fut
        key = self._render_key(user, view_id, show_hidden, locale, role)
        wanted = tuple(panels) if panels else None
        gen = self.gen
        with self._render_lock:
            rec = self._renders.get(key)
            if rec is not None and self._fresh(rec, gen, wanted, key):
                return _done(self._answer(rec, since, wanted, as_))
            jk = (key, user, gen, wanted)
            job = self._inflight.get(jk)
            if job is None:
                job = self.et.submit_at(EngineThread.VIEW, self._render_job, jk, key, user, view_id, show_hidden, locale, wanted)
                self._inflight[jk] = job
        return _then(job, lambda rec: self._answer(rec, since, wanted, as_))

    def _render_key(self, user: Optional[str], what: str, show_hidden: bool = False, locale: Optional[str] = None,
                    role: Optional[str] = None) -> Tuple:
        """Whose page it is: ``""`` for everybody without inputs of their own who is not an administrator."""
        who = ""
        if user:
            if user in self._private_users:
                who = user
            else:
                if role is None:
                    role = (self.store.account(user_key(user)) or {}).get("role")
                if role == "admin":
                    who = user
        return (who, what, bool(show_hidden), locale or self.settings.locale)

    def _fresh(self, rec: Dict[str, Any], gen: int, wanted: Optional[Tuple], key: Tuple) -> bool:
        """Whether the asked panels are known as of ``gen`` - or, for a user with inputs of their own (a calculation of
        their own), checked lately with no shared input and nothing at the desk changed since (only the market moved)."""
        throttle = self.settings.private_refresh
        recent = time.monotonic() - throttle if (throttle > 0 and key[0] and key[0] in self._private_users) else None
        shared = self._shared_changes(rec)
        panels = rec["panels"]
        for pid in (wanted if wanted is not None else rec["order"]):
            p = panels.get(pid)
            if p is None:
                continue                                 # (not a panel of the page: nothing to make)
            if p["entry"] is None:
                return False
            if p["checked"] != gen and (recent is None or p["at"] < recent or p.get("inputs") != shared
                                         or p.get("desk") != self.desk_changes):
                return False                             # (a shared input or the desk changed since it was checked: at once)
        return True

    def _shared_changes(self, rec: Dict[str, Any]) -> int:
        book = self.books.get(rec.get("book") or "tto")
        return book.engine.input_changes if book is not None else 0

    def _render_job(self, jk, key, user, view_id, show_hidden, locale, wanted) -> Dict[str, Any]:
        try:
            gen = self.gen
            with self._render_lock:
                prev = self._renders.get(key)
            rec = self._render(prev, key, user, view_id, show_hidden, locale, wanted, gen)
            self._keep(rec["key"], rec)
            return rec
        finally:
            if jk is not None:
                with self._render_lock:
                    self._inflight.pop(jk, None)

    def _keep(self, key: Tuple, rec: Dict[str, Any]) -> None:
        with self._render_lock:
            self._renders.pop(key, None)
            self._renders[key] = rec
            while len(self._renders) > self.RENDERS_KEPT:
                self._renders.pop(next(iter(self._renders)))

    def _forget_renders(self, user: str) -> None:
        """The pages and header kept for one user (their own inputs changed: made again at once)."""
        with self._render_lock:
            for key in [k for k in self._renders if k[0] == user]:
                self._renders.pop(key, None)

    def _formulas_changed(self, scope: str) -> None:
        """An input got or lost a formula (or one was stopped) in a scope - a user's own, or ``""`` the desk's: the pages
        kept are made again (a cell's ƒ, its formula, whatever its value did)."""
        if scope:
            self._forget_renders(scope)
        else:
            with self._render_lock:
                self._renders.clear()

    @staticmethod
    def _still(meta, calc: Calc) -> bool:
        """Whether what was made from ``calc`` (``meta``: its calculation, layout, epoch and the masks of what it read)
        is still what it would be: nothing it read was invalidated since."""
        serial, layout, epoch, mask = meta
        if serial != calc.serial or layout != calc.engine.layout:
            return False
        m = calc.changed_since(epoch)
        return m is not None and not (m & mask)

    def _made(self, old: Optional[Dict[str, Any]], calc: Calc, gen: int, reusable: bool, make: Callable[[], Any]):
        """A kept part (a panel, the header) as of ``gen``: the one kept if nothing it read changed, or made again."""
        now = time.monotonic()
        desk = self.desk_changes                  # (before it is made: a change while it is made counts after)
        if old is not None and old["entry"] is not None:
            if old["checked"] == gen:
                return old
            if reusable and old["meta"] is not None and self._still(old["meta"], calc):
                meta = old["meta"]
                return dict(old, checked=gen, at=now, meta=(meta[0], meta[1], calc.epoch, meta[3]),
                            inputs=calc.engine.input_changes, desk=desk)
        calc.track = 0
        try:
            entry = make()
            mask = calc.track
        finally:
            calc.track = None
        meta = (calc.serial, calc.engine.layout, calc.epoch, mask) if reusable else None
        same = old is not None and old["entry"] is not None and old["entry"] == entry
        return {"entry": entry, "meta": meta, "content": old["content"] if same else gen, "checked": gen, "at": now,
                "inputs": calc.engine.input_changes, "desk": desk}      # (shared inputs / desk changes so far: _fresh)

    def _answer(self, rec: Dict[str, Any], since: Optional[int], wanted: Optional[Tuple],
                as_: Optional[str] = None) -> Dict[str, Any]:
        """What the browser gets of a kept page (never changing what is kept)."""
        kind = "p" if rec["key"][0] else "s"
        if as_ is not None and as_ != kind:
            since = None                                 # (the browser has the other page: everything)
        ids = set(wanted) if wanted is not None else None
        panels = [rec["panels"][pid] for pid in rec["order"] if ids is None or pid in ids]
        panels = [p for p in panels if p["entry"] is not None and not p["entry"].get("skip")]
        if since is not None:
            panels = [p for p in panels if p["content"] > since]
            if not panels:
                return {"id": rec["top"]["id"], "gen": rec["gen"], "unchanged": True, "as": kind}
        out = dict(rec["top"])
        out["gen"] = rec["gen"]
        out["ms"] = rec["ms"]
        out["panels"] = [p["entry"] for p in panels]
        out["ids"] = rec["ids"]
        out["as"] = kind
        if since is not None or wanted is not None:
            out["partial"] = True
        return out

    def _render(self, prev, key, user, view_id, show_hidden, locale, wanted, gen) -> Dict[str, Any]:
        """A page's kept panels as of ``gen`` (the calculation thread): those asked for are checked or made again."""
        v = self.view_index.get(view_id)
        if v is None:
            raise ServiceError("sayfa bulunamadı: %s" % view_id, 404)
        if v.get("admin") and user is not None and not self._is_admin(user):
            raise ServiceError("bu sayfa yalnızca yöneticilere açıktır", 403)
        book = self.books[v["book"]]
        calc = self._calc(user, book)
        if not key[0] and calc is not book.engine.shared:
            # a user with inputs of their own the key did not know of (it never shares their page): theirs
            with self._render_lock:
                self._private_users.add(user)
            key = (user,) + tuple(key[1:])
            with self._render_lock:
                prev = self._renders.get(key)
        loc = numfmt.get_locale(locale or self.settings.locale)
        overlay = self._overlay(user, book) if user else None
        R = self.renderers[book.id]
        # the sheet explorer is the administrators' (a page everybody shares never names it)
        explorer = bool(key[0]) and self._is_admin(user)
        old = prev["panels"] if prev is not None else {}
        want = set(wanted) if wanted is not None else None
        t0 = time.time()
        panels: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        types: List[str] = []

        def part(pid: str, ptype: str, reusable: bool, make: Callable[[], Dict[str, Any]]) -> None:
            order.append(pid)
            types.append(ptype)
            o = old.get(pid)
            if want is not None and pid not in want:
                # not asked for (another tab): kept as it is, checked when it is asked for
                panels[pid] = o if o is not None else {"entry": None, "meta": None, "content": 0, "checked": -1, "at": 0.0}
                return
            panels[pid] = self._made(o, calc, gen, reusable, make)

        sheet_default = v.get("sheet")
        charts = list(book.model.sheets[book.model.sheet_index[sheet_default]].charts) if sheet_default else []
        for p in v["panels"]:
            if p.get("hidden") and not show_hidden:
                continue
            sheet = p.get("sheet", sheet_default)
            if sheet is not None and sheet not in book.model.sheet_index:
                continue                               # a table of the dashboard's own that does not fit this file
            # what reads the workbook only is made again when what it read changed; a panel completed with what the
            # Broker Chat, the trades or another workbook say is made every time
            reusable = p["type"] in ("table", "notes", "chart", "custom") and not p.get("append") and not p.get("source")
            ptype = "table" if p["type"] == "generated" else p["type"]
            part(p.get("id"), ptype, reusable,
                 lambda p=p, sheet=sheet: self._panel(p, v, book, calc, R, loc, overlay, user, sheet, charts, show_hidden, explorer))
        if not any(p["type"] == "chart" for p in v["panels"]):
            for i, ch in enumerate(charts):
                part("chart%d" % i, "chart", True, lambda ch=ch, i=i: self._sheet_chart(R, calc, ch, loc, "chart%d" % i))
        sheet_obj = book.model.sheets[book.model.sheet_index[sheet_default]] if sheet_default else None
        if sheet_obj is not None:
            # pictures pasted on the sheet come after the tables
            for i, img in enumerate(sheet_obj.images):
                part("image%d" % i, "image", True, lambda i=i, img=img: {
                    "id": "image%d" % i, "type": "image", "title": v.get("image_titles", {}).get(str(i)) or "Excel'deki resim",
                    "src": "/api/image?book=%s&sheet=%s&i=%d" % (book.id, _quote(sheet_default), i),
                    "width": img.get("width"), "height": img.get("height"), "hidden": False, "wide": True})
        if show_hidden:
            # scratch cells that belong to no table: listed, so that nothing the workbook computes is missing
            for k, (sheet_name, rest) in enumerate(self._leftover_cells(v)):
                extra = "" if sheet_name == sheet_default else " (%s)" % sheet_name
                pid = "rest" if k == 0 else "rest%d" % k
                part(pid, "table", True, lambda pid=pid, sheet_name=sheet_name, rest=rest, extra=extra: {
                    "id": pid, "type": "table", "title": "Diğer hücreler · tablolara girmeyen formül ve değerler" + extra,
                    "hidden": True, "wide": False, "collapsed": False, "note": None,
                    "data": R.cells_table(calc, sheet_name, rest, loc, overlay)})
        # a chart whose data could not be read is no panel at all (as before): left out of the page
        shown = [(pid, t) for pid, t in zip(order, types) if not (panels[pid]["entry"] or {}).get("skip")]
        note = v.get("note")
        if v.get("replay_note") and self.mode != "live" and not getattr(book, "recorded", True):
            note = v["replay_note"]                    # the workbook was saved without market data
        top = {"id": v["id"], "title": v["title"], "book": book.id, "sheet": sheet_default, "note": note}
        top.update(view_layout(v, [pid for pid, _ in shown]))
        hidden = self._hidden_pages(user if key[0] else "")
        links = [link for link in self._shortcuts(v) if link["page"] not in hidden]      # (an administrators' page: theirs)
        if links:
            top["links"] = links
        return {"key": key, "top": top, "order": order, "ids": ["%s:%s" % (pid, t) for pid, t in shown],
                "panels": panels, "gen": gen, "ms": int((time.time() - t0) * 1000), "book": book.id}

    @staticmethod
    def _sheet_chart(R, calc: Calc, ch: Dict[str, Any], loc, pid: str) -> Dict[str, Any]:
        try:
            data = R.chart(calc, ch, loc)
        except Exception:  # noqa: BLE001 - a chart that cannot be read is left out
            return {"skip": True}
        return {"id": pid, "type": "chart", "title": data["title"], "data": data, "anchor": ch["anchor"],
                "hidden": False, "wide": False}

    def _view(self, user, view_id, show_hidden, locale) -> Dict[str, Any]:
        """A whole page made from scratch, nothing kept (the calculation thread)."""
        key = self._render_key(user, view_id, show_hidden, locale)
        return self._answer(self._render(None, key, user, view_id, show_hidden, locale, None, self.gen), None, None)

    # ================================================================== tables of many pages at once
    #: the tables one request may ask for (a launchpad, the side drawer, a pop-out window)
    MAX_PANEL_ITEMS = 200

    def panels(self, user: Optional[str], items: Any, locale: Optional[str] = None,
               role: Optional[str] = None) -> Dict[str, Any]:
        return self.panels_future(user, items, locale, role).result()

    def panels_future(self, user: Optional[str], items: Any, locale: Optional[str] = None,
                      role: Optional[str] = None) -> "concurrent.futures.Future":
        """Tables of any pages in one answer - what a launchpad, the side drawer or a pop-out window shows (a browser has
        six connections to the dashboard: one request, however many pages the tables come from).

        ``items``: ``[{"view", "panel", "key"?, "rows"?, "cols"?, "all"?, "since"?, "as"?}, ...]``.  Each page is asked
        for once, the way its own page asks (``view_future`` with the panels wanted, ``since`` the oldest generation
        the browser has of them, ``as`` the page it has them of), so a page's kept panels serve both.  ``rows`` /
        ``cols``: a part of the table (the item's own choice), cut out of a copy here.

        The answer is keyed by ``key`` (default ``"view/panel"``: panel ids repeat across pages): ``{"gen", "as",
        "entry": the panel as its page draws it, "book", "page", "tab"}``; ``{"gen", "as", "unchanged": true}`` when it did
        not change since; ``{"missing": true, "status", "error"}`` for a table that is not there (any more) or not this
        user's to see - one such item never fails the others."""
        reqs = self._panel_requests(items)
        admin = (role == "admin") if role is not None else self._is_admin(user)
        out: Dict[str, Dict[str, Any]] = {}
        groups: Dict[Tuple[str, bool], List[Dict[str, Any]]] = {}
        for r in reqs:
            groups.setdefault((r["view"], r["all"]), []).append(r)
        waits: List[Tuple[List[Dict[str, Any]], "concurrent.futures.Future"]] = []
        for (vid, show), rs in groups.items():
            v = self.view_index.get(vid)
            if v is None or (v.get("admin") and not admin):
                why = ("bu tablo artık yok: sayfası kaldırılmış", 404) if v is None else ("erişim yok: bu sayfa yalnızca yöneticilere açıktır", 403)
                for r in rs:
                    out[r["key"]] = _missing(r, *why)
                continue
            gens = [r["since"] for r in rs]
            kinds = {r["as"] for r in rs}
            as_ = kinds.pop() if len(kinds) == 1 else None
            since = min(gens) if as_ is not None and all(g is not None for g in gens) else None
            pids = list(dict.fromkeys(r["panel"] for r in rs))
            waits.append((rs, self.view_future(user, vid, show, locale, since, pids, role, as_)))

        def assemble(_):
            for rs, fut in waits:
                try:
                    res = fut.result()
                except ServiceError as exc:
                    for r in rs:
                        out[r["key"]] = _missing(r, str(exc), exc.status)
                    continue
                except Exception as exc:  # noqa: BLE001 - one page that fails must not take the others with it
                    self.ops.failure("panels %s" % rs[0]["view"], exc)
                    for r in rs:
                        out[r["key"]] = _missing(r, "sunucu hatası: %s" % (str(exc)[:200] or type(exc).__name__), 500)
                    continue
                for r in rs:
                    out[r["key"]] = _panel_answer(r, res)
            return {"gen": self.gen, "panels": out}

        return _then(_all_done([f for _, f in waits]), assemble)

    def _panel_requests(self, items: Any) -> List[Dict[str, Any]]:
        if not isinstance(items, list) or not items:
            raise ServiceError("items listesi gerekli")
        if len(items) > self.MAX_PANEL_ITEMS:
            raise ServiceError("bir istekte en fazla %d tablo istenebilir" % self.MAX_PANEL_ITEMS)
        out: List[Dict[str, Any]] = []
        keys = set()
        for x in items:
            if not isinstance(x, dict):
                raise ServiceError("tablo isteği geçersiz")
            vid, pid = x.get("view"), x.get("panel")
            if not isinstance(vid, str) or not lay.PAGE_ID.match(vid) or not isinstance(pid, str) or not lay.PANEL_ID.match(pid):
                raise ServiceError("tablo isteği geçersiz: sayfa ve tablo adı gerekli")
            key = x.get("key")
            if key is None:
                key = "%s/%s" % (vid, pid)
            if not isinstance(key, str) or not 0 < len(key) <= 120:
                raise ServiceError("tablo isteğinin anahtarı geçersiz")
            if key in keys:
                raise ServiceError("aynı anahtarla iki tablo istendi: %s" % key)
            keys.add(key)
            try:
                rows, cols = lay.rows_choice(x.get("rows")), lay.cols_choice(x.get("cols"))
            except lay.LayoutError as exc:
                raise ServiceError(str(exc))
            since = x.get("since")
            if isinstance(since, bool) or not isinstance(since, int):
                since = None
            kind = x.get("as") if x.get("as") in ("s", "p") else None
            out.append({"key": key, "view": vid, "panel": pid, "rows": rows, "cols": cols, "all": x.get("all") is True,
                        "since": since, "as": kind})
        return out

    def _panel(self, p, v, book, calc, R, loc, overlay, user, sheet, charts, show_hidden, explorer) -> Dict[str, Any]:
        """One panel of a page as the browser draws it."""
        entry = {"id": p.get("id"), "type": p["type"], "title": p.get("title", ""), "hidden": bool(p.get("hidden")),
                 "wide": bool(p.get("wide")), "collapsed": bool(p.get("collapsed")), "note": p.get("note")}
        if p.get("action"):
            entry["action"] = p["action"]          # a button of the dashboard's own in the panel's header
        if p.get("add"):
            # a list of bonds: where an ISIN added goes, and which list of the catalog it is
            where = p.get("sheet", v.get("sheet"))
            lst = p["add"]["list"]
            entry["add"] = dict(p["add"], ref=lst if "!" in lst else "%s!%s" % (where, lst), book=v["book"],
                                name=p["add"].get("name") or v["id"])     # another page's list: by its name
        if p.get("grow"):
            entry["grow"] = p["grow"]               # more rows than in use: the page shows the filled ones and one more
        if p.get("card"):
            entry["card"] = p["card"]               # a click on ▸ opens the bond's card
        if p.get("flags"):
            entry["flags"] = p["flags"]             # ☆ / ★: onto / off the trading list
        if p.get("quote"):
            entry["quote"] = p["quote"]             # "Kota mesajı": its rows as a message to send
        if p.get("trade"):
            entry["trade"] = p["trade"]             # "İşlem gir": a row as a trade to enter
        try:
            if p.get("note_ref"):
                # the explanation the workbook keeps in a cell next to the chart / table
                nsi, nrc = book.cell(p["note_ref"] if "!" in p["note_ref"] else "%s!%s" % (sheet, p["note_ref"]))
                text = calc.get(nsi, *divmod(nrc, COLS))
                if isinstance(text, str) and text.strip():
                    entry["note"] = text.strip()
            if p["type"] in ("table", "notes"):
                entry["range"] = p["range"]
                rng = p["range"]
                if p.get("max_rows"):
                    # a long helper table: its first rows here, all of it in the sheet explorer (administrators)
                    r1, c1, r2, c2 = parse_range(rng)
                    if r2 - r1 + 1 > int(p["max_rows"]):
                        rng = "%s:%s" % (a1(r1 * COLS + c1), a1((r1 + int(p["max_rows"]) - 1) * COLS + c2))
                        entry["note"] = ("İlk %d satır gösteriliyor (toplam %d)." % (int(p["max_rows"]), r2 - r1 + 1)
                                         + (" Tamamı: Sayfa gezgini → %s!%s" % (sheet, p["range"]) if explorer else ""))
                # columns hidden in Excel stay out of the way until the helper tables are asked for
                entry["data"] = R.table(calc, sheet, rng, loc, overlay, show_hidden=show_hidden)
                self._mark_formulas(entry["data"], book, sheet, user if overlay else None)
                if p.get("lift", True):
                    own = _lift_title(entry["data"])
                    if own and not p.get("keep_title"):
                        entry["title"] = own
                if p.get("cols"):
                    _pick_columns(entry["data"], p["cols"])
                if p.get("header"):
                    _column_captions(entry["data"], p["header"])
                if p.get("append") == "asw_fx":
                    self._asw_fx_columns(book, user, entry["data"], loc)
                elif p.get("append") == "broker_bonds":
                    self._dibs_broker_columns(book, user, entry["data"], loc)
                elif p.get("append") == "dibs_live":
                    self._dibs_live_columns(book, user, entry["data"], loc)
                elif p.get("append") == "universe":
                    self._universe_columns(book, user, entry["data"], loc)
                elif p.get("append") == "borsa_spread":
                    self._borsa_spread_columns(book, calc, user, entry["data"], loc, p["range"])
            elif p["type"] == "chart":
                spec = p.get("spec")
                if spec is None:
                    idx = p.get("chart", 0)
                    if idx < len(charts):
                        spec = charts[idx]
                if spec is not None:
                    entry["data"] = R.chart(calc, spec, loc)
                    entry["title"] = p.get("title") or entry["data"]["title"]
            elif p["type"] == "custom":
                entry["component"] = p.get("component")
            elif p["type"] == "generated":
                entry["type"] = "table"             # a table of the dashboard's own, from no range of a sheet
                if p.get("source") == "dibs_tape":
                    entry["data"] = self._tape_table(user, loc)
                elif p.get("source") == "dibs_trading":
                    entry["data"] = self._trading_table(user, loc)
            if p.get("title_ref"):
                # the caption the workbook keeps in a cell above the chart / table
                tsi, trc = book.cell(p["title_ref"] if "!" in p["title_ref"] else "%s!%s" % (sheet, p["title_ref"]))
                text = calc.get(tsi, *divmod(trc, COLS))
                if isinstance(text, str) and text.strip():
                    entry["title"] = " ".join(text.split())
        except ServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - one broken panel must not take the page down
            entry["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        return entry

    def _mark_formulas(self, data: Optional[Dict[str, Any]], book: Book, sheet: str, user: Optional[str]) -> None:
        """The inputs of a table typed as a formula, as ``user`` sees them (theirs and the desk's): ``ff`` the formula's
        text (the cell shows its value with a small ƒ; F2 edits the text), ``fe`` why it stopped or what its error means."""
        fx = self.formulas
        if fx is None or not fx.active or not data or not data.get("r") or not data.get("c"):
            return
        si = book.model.sheet_index.get(sheet)
        marks = fx.marks(user, book.id, si) if si is not None else None
        if not marks:
            return
        rows = {r: i for i, r in enumerate(data["r"])}
        cols = {c: j for j, c in enumerate(data["c"])}
        for (r, c), e in marks.items():
            i, j = rows.get(r), cols.get(index_to_col(c))
            if i is None or j is None:
                continue
            cell = data["rows"][i][j]
            if not cell or cell.get("sk") or "i" not in cell:
                continue
            cell["ff"] = e.text
            why = e.error or (e.note if cell.get("k") == "e" else None)
            if why:
                cell["fe"] = why

    def _leftover_cells(self, v: Dict[str, Any]) -> List[Tuple[str, List[Tuple[int, int]]]]:
        """Cells of the page's sheets that hold a formula or a value but lie in none of the page's tables:
        ``[(sheet, [(row, col), ...]), ...]`` (sheets without such cells are left out)."""
        cached = self._leftover_cache.get(v["id"])
        if cached is not None:
            return cached
        out: List[Tuple[str, List[Tuple[int, int]]]] = []
        main = v.get("sheet")
        book = self.books[v["book"]]
        sheets = [main] if main else []
        for p in v["panels"]:
            # (a "borrowed" panel shows a few cells of another page's sheet: that sheet stays the other page's)
            if p.get("sheet") and not p.get("borrowed") and p["sheet"] not in sheets and p["sheet"] in book.model.sheet_index:
                sheets.append(p["sheet"])
        for sheet_name in sheets:
            sh = book.model.sheets[book.model.sheet_index[sheet_name]]
            boxes = []
            for p in v["panels"]:
                if p["type"] in ("table", "notes") and p.get("sheet", main) == sheet_name:
                    try:
                        boxes.append(parse_range(p["range"]))
                    except Exception:  # noqa: BLE001
                        continue
                if p.get("sheet", main) == sheet_name:
                    for key in ("note_ref", "title_ref"):
                        if p.get(key) and "!" not in p[key]:
                            r, c = divmod(parse_a1(p[key]), COLS)
                            boxes.append((r, c, r, c))
            cells = set(sh.fml) | set(sh.members) | {rc for rc, val in sh.consts.items()
                                                     if val is not None and not (isinstance(val, str) and not val.strip())}
            rest = []
            for rc in sorted(cells):
                r, c = divmod(rc, COLS)
                if not any(r1 <= r <= r2 and c1 <= c <= c2 for (r1, c1, r2, c2) in boxes):
                    rest.append((r, c))
            if rest:
                out.append((sheet_name, rest))
        self._leftover_cache[v["id"]] = out
        return out

    def _shortcuts(self, v: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The sheet's own hyperlinks ("go to OIS_MAIN!A7") as page + panel targets of the dashboard."""
        cached = self._shortcut_cache.get(v["id"])
        if cached is not None:
            return cached
        out: List[Dict[str, Any]] = []
        book = self.books[v["book"]]
        sheet_name = v.get("sheet")
        sheet = book.model.sheets[book.model.sheet_index[sheet_name]] if sheet_name else None
        by_sheet: Dict[str, Dict[str, Any]] = {}
        for other in self.views:
            if other["book"] == v["book"] and other.get("sheet"):
                by_sheet.setdefault(other["sheet"], other)
        for link in (sheet.links if sheet is not None else []):
            target_sheet, _, addr = link["location"].rpartition("!")
            target_sheet = target_sheet.strip("'")
            label = (link.get("display") or "").strip()
            if not label or not addr:
                continue
            try:
                r, c = divmod(parse_a1(addr.replace("$", "").split(":")[0]), COLS)
            except Exception:  # noqa: BLE001
                continue
            if target_sheet == bl.SHEET and "tto" in self.books:
                out.append({"label": label, "page": "blotter", "panel": None, "ref": link["location"]})
                continue
            page = by_sheet.get(target_sheet)
            if page is None:
                continue
            best, best_score = None, None
            for p in page["panels"]:
                if p["type"] not in ("table", "notes") or p.get("hidden") or p.get("sheet", target_sheet) != target_sheet:
                    continue
                try:
                    r1, c1, r2, c2 = parse_range(p["range"])
                except Exception:  # noqa: BLE001
                    continue
                if r1 <= r <= r2 and c1 <= c <= c2:
                    score = (0, (r2 - r1 + 1) * (c2 - c1 + 1))            # inside: the tightest panel
                else:
                    # the link points at a heading just above / beside the table it means
                    dr = r1 - r if r1 >= r else (r - r2 if r > r2 else 0)
                    dc = c1 - c if c1 >= c else (c - c2 if c > c2 else 0)
                    score = (1, dr * 4 + dc * 12 + (40 if r1 < r else 0))
                if best_score is None or score < best_score:
                    best, best_score = p, score
            out.append({"label": label, "page": page["id"], "panel": best.get("id") if best is not None else None,
                        "ref": link["location"]})
        self._shortcut_cache[v["id"]] = out
        return out

    def image(self, book_id: str, sheet: str, index: int) -> Tuple[bytes, str]:
        """A picture of the workbook: (bytes, mime type)."""
        import base64
        book = self._book(book_id)
        si = book.model.sheet_index.get(sheet)
        if si is None:
            raise ServiceError("sayfa bulunamadı: %s" % sheet, 404)
        images = book.model.sheets[si].images
        if not 0 <= index < len(images):
            raise ServiceError("resim bulunamadı", 404)
        return base64.b64decode(images[index]["data"]), images[index]["mime"]

    def header(self, user: Optional[str], locale: Optional[str] = None, since: Optional[int] = None,
               as_: Optional[str] = None) -> Dict[str, Any]:
        """Top strip: spot / TLREF / spot date ... read from MASA row 1-2 (labels) and its status row."""
        if self.et.here():
            return self._header(user, locale)
        return self.header_future(user, locale, since, None, as_).result()

    def header_future(self, user: Optional[str], locale: Optional[str] = None, since: Optional[int] = None,
                      role: Optional[str] = None, as_: Optional[str] = None) -> "concurrent.futures.Future":
        """The header strip as a future, kept like a page (see view_future): one for everybody without inputs of their
        own, made again when what it read changed; ``since``: ``{"unchanged": true}`` when it did not."""
        key = self._render_key(user, "#header", False, locale, role)
        gen = self.gen
        with self._render_lock:
            rec = self._renders.get(key)
            if rec is not None and self._fresh(rec, gen, None, key):
                return _done(self._header_answer(rec, since, as_))
            jk = (key, user, gen)
            job = self._inflight.get(jk)
            if job is None:
                job = self.et.submit_at(EngineThread.HEADER, self._header_job, jk, key, user, locale)
                self._inflight[jk] = job
        return _then(job, lambda rec: self._header_answer(rec, since, as_))

    def _header_job(self, jk, key, user, locale) -> Dict[str, Any]:
        try:
            gen = self.gen
            book = self.books.get("tto")
            with self._render_lock:
                prev = self._renders.get(key)
            calc = self._calc(user, book) if book is not None else None
            if book is not None and not key[0] and calc is not book.engine.shared:
                with self._render_lock:
                    self._private_users.add(user)
                key = (user,) + tuple(key[1:])
                with self._render_lock:
                    prev = self._renders.get(key)
            old = prev["panels"]["#"] if prev is not None else None
            if calc is None:
                part = {"entry": self._header(user, locale), "meta": None, "content": gen, "checked": gen, "at": time.monotonic()}
            else:
                part = self._made(old, calc, gen, True, lambda: {"items": self._header(user, locale)["items"]})
            rec = {"key": key, "panels": {"#": part}, "order": ["#"], "gen": gen, "book": "tto"}
            self._keep(key, rec)
            return rec
        finally:
            with self._render_lock:
                self._inflight.pop(jk, None)

    @staticmethod
    def _header_answer(rec: Dict[str, Any], since: Optional[int], as_: Optional[str] = None) -> Dict[str, Any]:
        part = rec["panels"]["#"]
        kind = "p" if rec["key"][0] else "s"
        if since is not None and part["content"] <= since and (as_ is None or as_ == kind):
            return {"gen": rec["gen"], "unchanged": True, "as": kind}
        out = dict(part["entry"], gen=rec["gen"])
        out["as"] = kind
        return out

    def _header(self, user, locale) -> Dict[str, Any]:
        book = self.books.get("tto")
        if book is None:
            return {"items": [], "gen": self.gen}
        loc = numfmt.get_locale(locale or self.settings.locale)
        calc = self._calc(user, book)
        R = self.renderers[book.id]
        si = book.model.sheet_index.get("MASA")
        items = []
        if si is not None:
            for col in range(parse_a1("F1") % COLS, parse_a1("N1") % COLS + 1):
                lab = calc.get(si, 1, col)
                cell = R.cell(calc, si, 2, col, loc)
                if type(lab) is str and lab:
                    item = {"label": lab, "text": cell.get("t", ""), "v": cell.get("v")}
                    # "Spot kaynağı" shows VIOP!AA8 (MANUEL / BBG): a click on it opens the manual spot
                    if MANUAL_SPOT["shown_as"] in formula_text(book, si, 2 * COLS + col):
                        item["edit"] = "spot"
                    items.append(item)
        return {"items": items, "gen": self.gen}

    def manual_spot(self, user: Optional[str]) -> Dict[str, Any]:
        """The manual USDTRY spot: what is typed (``None``: nothing, Bloomberg is used) and what the sheet says
        about it ("MANUEL", "BBG", "HATA: Bid>Ask").  Set through :meth:`set_inputs` like any shared input."""
        return self.et.call(self._manual_spot, user)

    def _manual_spot(self, user) -> Dict[str, Any]:
        book = self.books.get(MANUAL_SPOT["book"])
        out: Dict[str, Any] = {"book": MANUAL_SPOT["book"], "refs": {"bid": MANUAL_SPOT["bid"], "ask": MANUAL_SPOT["ask"]},
                               "bid": None, "ask": None, "source": "", "available": False}
        if book is None:
            return out
        calc = self._calc(user, book)
        try:
            cells = {k: book.cell(MANUAL_SPOT[k]) for k in ("bid", "ask", "status")}
        except (KeyError, ValueError):
            return out
        if not all(cells[k] in book.inputs for k in ("bid", "ask")):
            return out
        for k in ("bid", "ask"):
            si, rc = cells[k]
            v = calc.get(si, *divmod(rc, COLS))
            out[k] = v if type(v) is float and v > 0 else None
        si, rc = cells["status"]
        text = calc.get(si, *divmod(rc, COLS))
        out["source"] = text if isinstance(text, str) else ""
        out["available"] = True
        return out

    def cell_info(self, user: Optional[str], book_id: str, ref: str, locale: Optional[str] = None) -> Dict[str, Any]:
        return self.et.call(self._cell_info, user, book_id, ref, locale)

    def _cell_info(self, user, book_id, ref, locale) -> Dict[str, Any]:
        book = self._book(book_id)
        try:
            si, rc = book.cell(ref)
        except (KeyError, ValueError):
            raise ServiceError("hücre bulunamadı: %s" % ref, 404)
        r, c = divmod(rc, COLS)
        calc = self._calc(user, book)
        loc = numfmt.get_locale(locale or self.settings.locale)
        cell = self.renderers[book.id].cell(calc, si, r, c, loc, self._overlay(user, book) if user else None)
        d = book.inputs.get((si, rc))
        sheet = book.model.sheets[si]
        base = sheet.consts.get(rc)
        inp = None if d is None else {"scope": d.scope, "label": d.label, "kind": d.kind}
        e = self.formulas.entry(user, book.id, si, rc) if (self.formulas is not None and inp is not None) else None
        if e is not None:
            inp["formula"] = cell["ff"] = e.text           # (an input typed as a formula: its text, its value in "cell")
            if e.error:
                inp["error"] = cell["fe"] = e.error
        return {"ref": book.ref(si, rc), "formula": formula_text(book, si, rc), "cell": cell, "input": inp,
                "base": None if base is None or type(base) is XlError else base,
                "excel_cached": _to_json(sheet.cached.get(rc)) if rc in sheet.cached else None}

    def grid(self, user: Optional[str], book_id: str, sheet: str, rng: str, locale: Optional[str] = None) -> Dict[str, Any]:
        """Any rectangle of any sheet (the 'Sayfa gezgini')."""
        return self.et.call(self._grid, user, book_id, sheet, rng, locale)

    def _grid(self, user, book_id, sheet, rng, locale) -> Dict[str, Any]:
        book = self._book(book_id)
        if sheet not in book.model.sheet_index:
            raise ServiceError("sayfa bulunamadı: %s" % sheet, 404)
        try:
            r1, c1, r2, c2 = parse_range(rng)
        except Exception:  # noqa: BLE001
            raise ServiceError("aralık anlaşılamadı: %s" % rng)
        if (r2 - r1 + 1) * (c2 - c1 + 1) > 20000:
            raise ServiceError("aralık çok büyük (en fazla 20.000 hücre)")
        loc = numfmt.get_locale(locale or self.settings.locale)
        calc = self._calc(user, book)
        data = self.renderers[book.id].table(calc, sheet, rng, loc, self._overlay(user, book) if user else None,
                                             trim=False)
        self._mark_formulas(data, book, sheet, user)
        s = book.model.sheets[book.model.sheet_index[sheet]]
        return {"book": book.id, "sheet": sheet, "range": rng, "data": data, "gen": self.gen,
                "dims": [s.max_row, s.max_col]}

    def sheets(self, book_id: str) -> List[Dict[str, Any]]:
        book = self._book(book_id)
        return [{"name": s.name, "rows": s.max_row, "cols": s.max_col, "formulas": len(s.fml)} for s in book.model.sheets]

    def _book(self, book_id: str) -> Book:
        b = self.books.get(book_id)
        if b is None:
            raise ServiceError("çalışma kitabı bulunamadı: %s" % book_id, 404)
        return b

    # ================================================================== inputs
    # ================================================================== holidays
    #: the desk's holiday lists, per currency: (book, sheet, first row, last row, date column, name column or None).
    #: TRY is kept twice - the TRY workbook's list (date and name; every WORKDAY of the workbook reads it) and the ASW
    #: workbook's (dates) - and edited as one list.  USD and EUR are the dashboard's own (``extras.HOL_SHEET``): the FX
    #: value dates skip the holidays of both currencies of a pair.  The first list of each is the one the TRY workbook's
    #: formulas read.  The USD workbook's US holidays (SIFMA: its SOFR / USD OIS sheets) and FOMC meetings are shown beside
    #: them, read only.
    HOLIDAY_LISTS = {"TRY": (("tto", "Motor", 361, 523, "A", "B"), ("asw", "ASW", 2, 200, "LR", None)),
                     "USD": (("tto", ex.HOL_SHEET, ex.HOL_FIRST, ex.HOL_LAST) + ex.HOL_COLS["USD"],),
                     "EUR": (("tto", ex.HOL_SHEET, ex.HOL_FIRST, ex.HOL_LAST) + ex.HOL_COLS["EUR"],)}
    HOLIDAYS_US = ("sofr", "SOFR_FOMC!BO4:BO70")
    FOMC_DATES = ("sofr", "SOFR_FOMC!B74:B83")

    def holidays(self) -> Dict[str, Any]:
        """``{"lists": {"TRY" | "USD" | "EUR": {"items": [{"date", "name"}], "slots", "books"}}, "ccys", "us": [iso],
        "fomc": [iso]}`` - and the TRY list again as ``tr`` / ``slots`` / ``books``, as before.  The TRY list is the dates
        of both workbooks (a name from the TRY one)."""
        return self.et.call(self._holidays)

    def _holiday_cells(self, ccy: str = "TRY") -> List[Tuple[Book, List[Tuple[Tuple[int, int], Optional[Tuple[int, int]]]]]]:
        """A currency's holiday lists that are loaded: (book, [(date cell, name cell or None), ...])."""
        out = []
        for book_id, sheet, r1, r2, dcol, ncol in self.HOLIDAY_LISTS[ccy]:
            book = self.books.get(book_id)
            if book is None or sheet not in book.model.sheet_index:
                continue
            si = book.model.sheet_index[sheet]
            dc = parse_a1(dcol + "1") % COLS
            nc = parse_a1(ncol + "1") % COLS if ncol else None
            out.append((book, [((si, r * COLS + dc), (si, r * COLS + nc) if nc is not None else None) for r in range(r1, r2 + 1)]))
        return out

    def _holiday_list(self, ccy: str) -> Dict[str, Any]:
        days: Dict[str, str] = {}
        lists = self._holiday_cells(ccy)
        for book, cells in lists:
            calc = book.engine.shared
            for (si, rc), name_cell in cells:
                v = calc.get(si, *divmod(rc, COLS))
                if type(v) is not float or not 20000 < v < 80000:
                    continue
                iso = serial_to_date(v).isoformat()
                name = calc.get(name_cell[0], *divmod(name_cell[1], COLS)) if name_cell else None
                name = name.strip() if isinstance(name, str) else ""
                if name or iso not in days:
                    days[iso] = name or days.get(iso, "")
        return {"items": [{"date": d, "name": days[d]} for d in sorted(days)], "available": bool(lists),
                "slots": min((len(cells) for _, cells in lists), default=0), "books": [b.id for b, _ in lists]}

    def _calendar_serials(self, ccys) -> set:
        """The days (serials) the desk's holiday lists of these currencies close, together - the lists the TRY workbook's
        formulas read (Motor for TRY, ``extras.HOL_SHEET`` for USD and EUR).  On the calculation thread."""
        out: set = set()
        for ccy in ccys:
            spec = self.HOLIDAY_LISTS.get(ccy)
            cells = self._holiday_cells(ccy)[:1] if spec else []
            for book, rows in cells:
                calc = book.engine.shared
                for (si, rc), _ in rows:
                    v = calc.get(si, *divmod(rc, COLS))
                    if type(v) is float and 20000 < v < 80000:
                        out.add(int(v))
        return out

    def holiday_dates(self, ccys) -> frozenset:
        """The days the desk's holiday lists of these currencies close, together (dates) - from any thread."""
        return frozenset(serial_to_date(s) for s in self.et.call(self._calendar_serials, tuple(ccys)))

    def _holidays(self) -> Dict[str, Any]:
        lists = {ccy: self._holiday_list(ccy) for ccy in self.HOLIDAY_LISTS}
        tr = lists["TRY"]

        def dates(where) -> List[str]:
            book = self.books.get(where[0])
            if book is None:
                return []
            try:
                cells = book.cells_of(where[1])
            except (KeyError, ValueError):
                return []
            vals = [book.engine.shared.get(si, *divmod(rc, COLS)) for si, rc in cells]
            return sorted(serial_to_date(v).isoformat() for v in vals if type(v) is float and 20000 < v < 80000)

        return {"available": any(x["available"] for x in lists.values()), "lists": lists, "ccys": list(lists),
                "tr": tr["items"], "slots": tr["slots"], "books": tr["books"],
                "us": dates(self.HOLIDAYS_US), "fomc": dates(self.FOMC_DATES), "gen": self.gen}

    def set_holidays(self, user: str, items: List[Any], ccy: Any = "TRY") -> Dict[str, Any]:
        """A currency's holidays (TRY when left out), for everybody: ``[{"date": "29.10.2026", "name": "Cumhuriyet"}, ...]``
        (a date as text or a serial; a day given twice once).  Written in date order - TRY to both workbooks -, the rows
        below stay empty."""
        user = self.require_user(user)
        ccy = str(ccy or "TRY").strip().upper()
        if ccy not in self.HOLIDAY_LISTS:
            raise ServiceError("tatil listesi yok: %s (%s)" % (ccy, ", ".join(self.HOLIDAY_LISTS)))
        if not isinstance(items, list):
            raise ServiceError("tatil listesi gerekli")
        days: Dict[str, str] = {}
        bad: List[str] = []
        for it in items:
            raw = it.get("date") if isinstance(it, dict) else it
            name = it.get("name") if isinstance(it, dict) else None
            name = " ".join(str(name).split())[:80] if name is not None else ""
            serial = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else parse_date(str(raw or ""))
            try:
                day = serial_to_date(serial) if serial is not None else None
            except (ValueError, OverflowError):
                day = None
            if day is None or not 2000 <= day.year <= 2100:
                bad.append(str(raw))
                continue
            iso = day.isoformat()
            if name or iso not in days:
                days[iso] = name
        if bad:
            raise ServiceError("tarih anlaşılamadı: %s" % ", ".join(bad[:8]))
        res = self.et.call_at(EngineThread.WRITE, self._set_holidays, user, ccy, days)
        self.bump()
        res["gen"] = self.gen
        return res

    def _set_holidays(self, user: str, ccy: str, days: Dict[str, str]) -> Dict[str, Any]:
        lists = self._holiday_cells(ccy)
        if not lists:
            raise ServiceError("%s tatil listesi bu dosyalarda yok" % ccy, 404)
        dates = sorted(days)
        room = min(len(cells) for _, cells in lists)
        if len(dates) > room:
            raise ServiceError("en çok %d tatil yazılabilir (%d verildi)" % (room, len(dates)))
        changed = False
        for book, cells in lists:
            engine = book.engine
            want: Dict[Tuple[int, int], Any] = {}
            for k, (dcell, ncell) in enumerate(cells):
                iso = dates[k] if k < len(dates) else None
                want[dcell] = float(date_to_serial(_dt.date.fromisoformat(iso))) if iso else None
                if ncell is not None:
                    want[ncell] = (days[iso] or None) if iso else None
            sets: Dict[Tuple[int, int], Any] = {}
            clears: List[Tuple[int, int]] = []
            for (si, rc), val in want.items():
                held = engine.input_value[si]
                if _same_value(val, engine.base_value(si, rc)):
                    if rc in held:
                        clears.append((si, rc))                  # the file's own value again
                elif rc not in held or not _same_value(held[rc], val):
                    sets[(si, rc)] = val
            for key in list(sets) + clears:
                if key not in book.inputs:
                    book.declare(book.ref(*key), scope="shared", group="adhoc-shared")
            if clears:
                engine.clear_inputs(clears)
                self.store.clear_shared_inputs(book.id, [book.ref(*k) for k in clears])
            if sets:
                engine.set_inputs(sets)
                self.store.set_shared_inputs(book.id, {book.ref(*k): _to_json(v) for k, v in sets.items()}, user)
            changed = changed or bool(sets or clears)
        if changed:
            # value dates moved for everybody - the forward pages, the blotter's tenors, the FX page's dates: every page
            # is made again (as after a change of the meeting calendar), the shared ones ahead of the first request
            self._note_private()
            self.warm()
            if ccy == "TRY":                             # the desk's market days too (read once a day otherwise)
                watch = getattr(self, "watch", None)
                if watch is not None:
                    watch._shut = ("", frozenset())
                self.ops._days.clear()
                desk = getattr(self, "desk", None)       # ... and the agenda's ("Her iş günü", "Ayın son iş günü")
                if desk is not None:
                    desk.holidays_changed()
        out = self._holidays()
        out["saved"] = len(dates)
        out["ccy"] = ccy
        return out

    def set_inputs(self, user: str, book_id: str, items: List[Dict[str, Any]], allow_adhoc: bool = False,
                   lang: Optional[str] = None, lenient: bool = False) -> Dict[str, Any]:
        """items: [{"ref": "Forward!D2", "value": "03.12.2026"} ...] (value None / "" clears).

        ``lang`` is the number format the texts were typed / copied in ("tr": 1.234,56 – "en": 1,234.56).
        ``lenient`` (a block pasted from Excel): cells that are not inputs are skipped and counted, not errors.
        A text that starts with ``=`` is a formula (inputformula.py): its result is the value, it is evaluated again
        whenever what it reads changes; refused - with the reason among the errors - as that module says.
        """
        user = self.require_user(user)
        res = self.et.call_at(EngineThread.WRITE, self._set_inputs, user, book_id, items, allow_adhoc, lang or self.settings.locale, lenient)
        self.bump()
        res["gen"] = self.gen
        return res

    def _set_inputs(self, user, book_id, items, allow_adhoc, lang="tr", lenient=False) -> Dict[str, Any]:
        from .inputformula import FormulaError
        book = self._book(book_id)
        if len(items) > 20000:
            raise ServiceError("çok fazla hücre")
        user_vals: Dict[Tuple[int, int], Any] = {}
        user_clear: List[Tuple[int, int]] = []
        shared_vals: Dict[Tuple[int, int], Any] = {}
        shared_clear: List[Tuple[int, int]] = []
        meetings: Dict[int, Any] = {}
        errors: List[str] = []
        skipped = 0
        user_forms: Dict[Tuple[int, int], Any] = {}      # cells typed as a formula: (sheet, rc) -> its entry
        shared_forms: Dict[Tuple[int, int], Any] = {}
        # a drop-down list Excel reads from a range (VİOP target's contracts, L97:X97) holds what those cells hold now
        calc = self._calc(user, book)
        for it in items:
            ref = it.get("ref")
            try:
                si, rc = book.cell(ref)
            except (KeyError, ValueError, AttributeError):
                errors.append("%s: hücre bulunamadı" % ref)
                continue
            raw = it.get("value")
            if isinstance(raw, str) and raw.strip().startswith("="):
                # a formula: checked (Bloomberg, a cycle, a cell that takes no formula ...) and evaluated over its scope
                d = book.inputs.get((si, rc))
                if d is None and lenient and not allow_adhoc:
                    skipped += 1
                    continue
                try:
                    val, ent = self.formulas.accept(user, book, si, rc, d, raw, calc,
                                                    list(user_forms.values()) + list(shared_forms.values()))
                except FormulaError as exc:
                    errors.append("%s: %s" % (ref, exc))
                    continue
                if ent.scope:
                    user_vals[(si, rc)] = val
                    user_forms[(si, rc)] = ent
                    if (si, rc) in user_clear:
                        user_clear.remove((si, rc))
                else:
                    shared_vals[(si, rc)] = val
                    shared_forms[(si, rc)] = ent
                    if (si, rc) in shared_clear:
                        shared_clear.remove((si, rc))
                continue
            user_forms.pop((si, rc), None)                # (a value typed after a formula in one write: the value)
            shared_forms.pop((si, rc), None)
            if self._meeting_date_cell(book, si, rc):
                try:
                    self.history.parse_dates([it.get("value")])
                except ValueError as exc:
                    errors.append("%s: %s" % (ref, exc))
                    continue
                meetings[rc // COLS] = it.get("value")
                continue
            d = book.inputs.get((si, rc))
            if d is None:
                if lenient and not allow_adhoc:
                    skipped += 1
                    continue
                if not allow_adhoc:
                    errors.append("%s: girdi hücresi değil" % ref)
                    continue
                book.declare(book.ref(si, rc), scope="user", group="adhoc")
                d = book.inputs[(si, rc)]
            sheet = book.model.sheets[si]
            fmt = book.model.numfmts[sheet.styles.get(rc, 0)] if sheet.styles.get(rc, 0) < len(book.model.numfmts) else "General"
            try:
                val = parse_input(it.get("value"), numfmt.is_percent_format(fmt), numfmt.is_date_format(fmt),
                                  d.kind, book.options_for(si, rc, calc), lang, d.aliases)
            except InputError as exc:
                errors.append("%s: %s" % (ref, exc))
                continue
            if d.scope == "shared":
                if val is None and rc in sheet.fml:
                    shared_clear.append((si, rc))      # a desk input with a formula default: the formula, for everybody
                else:
                    shared_vals[(si, rc)] = val
            elif val is None and (rc in sheet.fml or d.group == "adhoc"):
                # blanking a formula default = back to the formula; blanking a value typed over any other cell
                # ("elle değer") = back to what the workbook holds there
                user_clear.append((si, rc))
            else:
                user_vals[(si, rc)] = val
        calendar = None
        if meetings:
            # first, so that steps typed with the dates land on the meetings as the new list has them
            try:
                calendar = self.history._typed_rows(user, meetings)
            except ServiceError as exc:
                errors.append("toplantı takvimi: %s" % exc)
        if shared_clear:
            book.engine.clear_inputs(shared_clear)
            self.store.clear_shared_inputs(book.id, [book.ref(si, rc) for si, rc in shared_clear])
        if shared_vals:
            book.engine.set_inputs(shared_vals)
            self.store.set_shared_inputs(book.id, {book.ref(si, rc): _to_json(v) for (si, rc), v in shared_vals.items()}, user,
                                         {book.ref(si, rc): e.text for (si, rc), e in shared_forms.items()})
            if any(book.inputs[k].group == "ret" for k in shared_vals):
                self.store.add_ret_history(user, self._ret_rows(book))
        if shared_vals or shared_clear:
            self.formulas.wrote(book, "", shared_vals, shared_clear, shared_forms)
        if user_vals or user_clear:
            ov = dict(self._overlay(user, book))
            ov.update(user_vals)
            for k in user_clear:
                ov.pop(k, None)
            self._overlays[(user, book.id)] = ov
            book.engine.set_user_inputs(user, ov)
            if user_vals:
                self.store.set_user_inputs(user, book.id, {book.ref(si, rc): _to_json(v) for (si, rc), v in user_vals.items()},
                                           {book.ref(si, rc): e.text for (si, rc), e in user_forms.items()})
            if user_clear:
                self.store.clear_user_inputs(user, book.id, [book.ref(si, rc) for si, rc in user_clear])
            self.formulas.wrote(book, user, user_vals, user_clear, user_forms)
            self._note_private(user)
        if calendar:
            self._note_private()                        # (what was typed per meeting moved, for everybody)
            self.warm()
        res: Dict[str, Any] = {"applied": len(shared_vals) + len(shared_clear) + len(user_vals) + len(user_clear)
                               + (len(meetings) if calendar else 0),
                               "errors": errors}
        if calendar:
            res["calendar"] = calendar
        if lenient:
            res["skipped"] = skipped
        return res

    @staticmethod
    def _meeting_date_cell(book: Book, si: int, rc: int) -> bool:
        """A meeting date of the workbook's list (OIS_MAIN!P10:P89): it changes through the calendar only, which moves
        what was typed per meeting along with it."""
        from .history import BOOK, MEETING_ROWS, OIS_SHEET
        if book.id != BOOK or book.model.sheets[si].name != OIS_SHEET:
            return False
        r, c = divmod(rc, COLS)
        return c == parse_a1("P1") % COLS and MEETING_ROWS[0] <= r <= MEETING_ROWS[1]

    @staticmethod
    def _moved_by_calendar(book: Book, si: int, rc: int) -> bool:
        """A cell the meeting calendar moves when the list of meetings shifts (history.py ``_set_calendar``): a meeting
        date (OIS_MAIN!P10:P89) or a step typed per meeting (``STEP_COLS`` of the same rows) - what it holds goes with its
        meeting, for the desk and for every user."""
        from .history import BOOK, MEETING_ROWS, OIS_SHEET, STEP_COLS
        if book.id != BOOK or book.model.sheets[si].name != OIS_SHEET:
            return False
        r, c = divmod(rc, COLS)
        return MEETING_ROWS[0] <= r <= MEETING_ROWS[1] and c in {parse_a1(x + "1") % COLS for x in ("P",) + STEP_COLS}

    def paste(self, user: str, book_id: str, anchor: str, text: str, allow_adhoc: bool = False,
              lang: Optional[str] = None) -> Dict[str, Any]:
        """Paste tab-separated text (copied from Excel) with its top-left corner at ``anchor``.

        Only input cells take values; everything else in the pasted block is skipped.
        """
        user = self.require_user(user)
        book = self._book(book_id)
        try:
            si, rc = book.cell(anchor)
        except (KeyError, ValueError):
            raise ServiceError("hücre bulunamadı: %s" % anchor, 404)
        matrix = parse_clipboard(text)
        r0, c0 = divmod(rc, COLS)
        items = []
        skipped = 0
        sheet = book.model.sheets[si].name
        for i, row in enumerate(matrix):
            for j, cellv in enumerate(row):
                key = (si, (r0 + i) * COLS + c0 + j)
                if key in book.inputs or allow_adhoc:
                    items.append({"ref": "%s!%s" % (sheet, a1(key[1])), "value": cellv})
                else:
                    skipped += 1
        if not items:
            raise ServiceError("yapıştırılan alanda girdi hücresi yok")
        res = self.set_inputs(user, book_id, items, allow_adhoc, lang)
        res["skipped"] = skipped
        res["rows"] = len(matrix)
        res["cols"] = len(matrix[0]) if matrix else 0
        return res

    def reset_inputs(self, user: str, book_id: str, refs: Optional[List[str]] = None, shared: bool = False) -> Dict[str, Any]:
        """Back to the workbook's own values (personal inputs; ``shared`` for desk inputs)."""
        user = self.require_user(user)
        res = self.et.call_at(EngineThread.WRITE, self._reset_inputs, user, book_id, refs, shared)
        self.bump()
        res["gen"] = self.gen
        return res

    def _reset_inputs(self, user, book_id, refs, shared) -> Dict[str, Any]:
        book = self._book(book_id)
        cells: List[Tuple[int, int]] = []
        if refs:
            for ref in refs:
                try:
                    cells.extend(book.cells_of(ref))
                except (KeyError, ValueError):
                    continue
        n = 0
        if shared:
            if any(self._meeting_date_cell(book, si, rc) for si, rc in cells):
                # the file's dates are those of the day it was saved: put back over the list, the steps would no longer
                # be those of their meetings
                raise ServiceError("toplantı tarihleri dosyadaki değere döndürülmez – listeyi Ayarlar → Toplantı takvimi'nden "
                                   "düzeltin (adımlar toplantısıyla taşınır)")
            keep = [c for c in cells if c in book.inputs and book.inputs[c].scope == "shared"]
            book.engine.clear_inputs(keep)
            self.store.clear_shared_inputs(book.id, [book.ref(si, rc) for si, rc in keep])
            self.formulas.cleared("", book, keep)        # (a formula there goes with its value)
            n = len(keep)
        else:
            ov = dict(self._overlay(user, book))
            targets = cells if refs else list(ov.keys())
            for k in targets:
                if k in ov:
                    del ov[k]
                    n += 1
            self._overlays[(user, book.id)] = ov
            book.engine.set_user_inputs(user, ov)
            if refs:
                self.store.clear_user_inputs(user, book.id, [book.ref(si, rc) for si, rc in targets])
            else:
                self.store.clear_user_inputs(user, book.id)
            self.formulas.cleared(user, book, targets if refs else None)
            self._note_private(user)
        return {"reset": n}

    def my_inputs(self, user: str) -> Dict[str, Any]:
        """The user's personal inputs: ``{"inputs": [{"book", "ref", "value", "label", "formula"?}]}`` - an input typed as
        a formula with its text and the value it has now."""
        user = self.require_user(user)
        out = []
        formulas = self.store.user_formulas(user)
        for (bid, ref), val in sorted(self.store.user_inputs(user).items()):
            book = self.books.get(bid)
            label = ""
            item: Dict[str, Any] = {"book": bid, "ref": ref, "value": val, "label": label}
            if book is not None:
                try:
                    cell = book.cell(ref)
                    if cell in self._retired_cells(book):
                        continue                       # an input that moved: dropped when the values are loaded
                    d = book.inputs.get(cell)
                    item["label"] = d.label if d else ""
                    if (bid, ref) in formulas:
                        item["formula"] = formulas[(bid, ref)]
                        now = self._overlays.get((user, bid), {}).get(cell, _NOT_SET)
                        if now is not _NOT_SET:
                            item["value"] = _to_json(now)
                except (KeyError, ValueError):
                    pass
            out.append(item)
        return {"inputs": out}

    # ================================================================== scenarios
    def scenarios(self, user: str) -> List[Dict[str, Any]]:
        return self.store.scenarios(self.require_user(user))

    def save_scenario(self, user: str, name: str) -> Dict[str, Any]:
        user = self.require_user(user)
        try:
            return self.store.save_scenario(user, name, self.store.user_inputs(user), self.store.user_formulas(user))
        except ValueError as exc:
            raise ServiceError(str(exc))

    def load_scenario(self, user: str, name: str) -> Dict[str, Any]:
        user = self.require_user(user)
        got = self.store.scenario(user, name)
        if got is None:
            raise ServiceError("senaryo bulunamadı: %s" % name, 404)
        values, formulas = got
        self.store.replace_user_inputs(user, values, formulas)      # (its formulas evaluated again over what is there now)
        self.et.call_at(EngineThread.WRITE, self._reload_user, user)
        self.bump()
        return {"loaded": name, "cells": len(values), "gen": self.gen}

    def delete_scenario(self, user: str, name: str) -> Dict[str, Any]:
        user = self.require_user(user)
        if not self.store.delete_scenario(user, name):
            raise ServiceError("senaryo bulunamadı: %s" % name, 404)
        return {"deleted": name}

    def _reload_user(self, user: str) -> None:
        for book in self.books.values():
            self._overlays.pop((user, book.id), None)
            ov = self._overlay(user, book)
            book.engine.set_user_inputs(user, ov)
        self._note_private(user)

    def _note_private(self, user: Optional[str] = None) -> None:
        """Whether a user has inputs of their own (``None``: every user, read again) - the pages they share follow it.
        Their kept pages and header are made again: what they typed shows at once."""
        if user is None:
            users = set(self.store.users_with_inputs())
            with self._render_lock:
                self._private_users = users
                self._renders.clear()
            return
        mine = bool(self.store.user_inputs(user))
        with self._render_lock:
            if mine:
                self._private_users.add(user)
            else:
                self._private_users.discard(user)
        self._forget_renders(user)
        watch = getattr(self, "watch", None)
        if watch is not None:
            watch._private_at.pop(user, None)            # (their watch list follows their change at once too)

    # ================================================================== the columns a user hides
    #: everybody looks at the tables their own way: table -> the columns this user hid, kept with the account
    #: (any computer they sign in from shows the same).  A table is named by the page (``v/<view>/<panel>`` for a
    #: table of a sheet, ``<page>/<table>`` for one of the dashboard's own); a column by its letter in the sheet or
    #: its caption.
    MAX_COLUMN_TABLES = 500
    MAX_HIDDEN_COLUMNS = 400
    MAX_COLUMN_BYTES = 256 * 1024                       # all of one user's choices together (a few KB in practice)
    _columns_lock = threading.Lock()

    def columns(self, user: Optional[str]) -> Dict[str, Any]:
        """The columns this user hid, table by table: ``{"tables": {"v/dibs/B5": ["B", "K"], ...}}`` - and, when they
        put the columns of a table in an order of their own, ``"order": {"v/dibs/B5": ["C", "A", "B", ...]}``."""
        key = self.require_user(user)
        out: Dict[str, Any] = {"tables": self.store.get("cols." + key) or {}}
        order = self.store.get("colorder." + key) or {}
        if order:
            out["order"] = order
        return out

    #: the columns of one table a user may name in an order of their own
    MAX_ORDER_COLUMNS = 400

    def set_column_order(self, user: Optional[str], table: Any, order: Any) -> Dict[str, Any]:
        """The order this user puts the columns of one table in (by the same keys as hiding them; an empty list: the
        sheet's own order again).  A column not named keeps its place after the named ones - one the table gains later
        comes last.  Kept with the account beside the hidden columns (``colorder.<user>``): on any computer the same."""
        key = self.require_user(user)
        if not isinstance(table, str) or not table.strip() or len(table) > 160:
            raise ServiceError("tablo adı geçersiz")
        if not isinstance(order, list) or any(not isinstance(c, str) or not c or len(c) > 160 for c in order):
            raise ServiceError("sütun sırası bir ad listesi olmalı")
        cols = list(dict.fromkeys(order))
        if len(cols) > self.MAX_ORDER_COLUMNS:
            raise ServiceError("bir tabloda en fazla %d sütun sıralanabilir" % self.MAX_ORDER_COLUMNS)
        with self._columns_lock:
            saved = self.store.get("colorder." + key) or {}
            if cols:
                saved[table] = cols
            else:
                saved.pop(table, None)
            if len(saved) > self.MAX_COLUMN_TABLES:
                raise ServiceError("en fazla %d tablonun sütun sırası değiştirilebilir – birkaçını Excel sırasına döndürün"
                                   % self.MAX_COLUMN_TABLES)
            if len(json.dumps(saved, ensure_ascii=False)) > self.MAX_COLUMN_BYTES:
                raise ServiceError("sütun sıralarının listesi çok uzun – birkaç tabloyu Excel sırasına döndürün")
            self.store.put("colorder." + key, saved)
        return {"table": table, "order": cols}

    def set_columns(self, user: Optional[str], table: Any, hidden: Any) -> Dict[str, Any]:
        """Hide these columns of one table from this user (an empty list shows every column again)."""
        key = self.require_user(user)
        if not isinstance(table, str) or not table.strip() or len(table) > 160:
            raise ServiceError("tablo adı geçersiz")
        if not isinstance(hidden, list) or any(not isinstance(c, str) or not c or len(c) > 160 for c in hidden):
            raise ServiceError("gizlenecek sütunlar bir ad listesi olmalı")
        cols = list(dict.fromkeys(hidden))
        if len(cols) > self.MAX_HIDDEN_COLUMNS:
            raise ServiceError("bir tabloda en fazla %d sütun gizlenebilir" % self.MAX_HIDDEN_COLUMNS)
        with self._columns_lock:
            saved = self.store.get("cols." + key) or {}
            if cols:
                saved[table] = cols
            else:
                saved.pop(table, None)
            if len(saved) > self.MAX_COLUMN_TABLES:
                raise ServiceError("en fazla %d tabloda sütun gizlenebilir – birkaç tablonun sütunlarını yeniden gösterin"
                                   % self.MAX_COLUMN_TABLES)
            if len(json.dumps(saved, ensure_ascii=False)) > self.MAX_COLUMN_BYTES:
                raise ServiceError("gizlenen sütunların listesi çok uzun – birkaç tablonun sütunlarını yeniden gösterin")
            self.store.put("cols." + key, saved)
        return {"table": table, "hidden": cols}

    # ================================================================== each user's own arrangement
    #: launchpads, the side drawer, the favourite pages and the page the dashboard opens on - kept with the account
    #: (``layout.<user>``; see layout.py): any computer they sign in from shows the same, an update keeps it
    MAX_LAYOUT_BYTES = 256 * 1024
    _layout_lock = threading.Lock()

    def layout(self, user: Optional[str]) -> Dict[str, Any]:
        """``{"launchpads": [{"name", "items": [...]}, ...], "drawer": [...], "favs": [...], "landing": "", "rev": n}``."""
        return lay.stored(self.store.get("layout." + self.require_user(user)))

    def set_layout(self, user: Optional[str], data: Any) -> Dict[str, Any]:
        """Replace the parts of this user's layout that ``data`` sends (``launchpads``, ``drawer``, ``favs``,
        ``landing``); the others stay.  Returns the whole layout as kept."""
        key = self.require_user(user)
        with self._layout_lock:
            cur = lay.stored(self.store.get("layout." + key))
            try:
                new = lay.change(cur, data)
            except lay.LayoutError as exc:
                raise ServiceError(str(exc))
            self._put_layout(key, new)
        return new

    def _put_layout(self, key: str, value: Dict[str, Any]) -> None:
        if len(json.dumps(value, ensure_ascii=False)) > self.MAX_LAYOUT_BYTES:
            raise ServiceError("düzeniniz çok büyüdü – birkaç launchpad'i ya da tabloyu kaldırın")
        self.store.put("layout." + key, value)

    def export_launchpad(self, user: Optional[str], name: Any) -> Tuple[bytes, str]:
        """One of this user's launchpads as a JSON file (to keep, or for a colleague to import): (bytes, file name)."""
        cur = self.layout(user)
        want = lay.name_key(name) if isinstance(name, str) else None
        lp = next((x for x in cur["launchpads"] if lay.name_key(x["name"]) == want), None)
        if lp is None:
            raise ServiceError("böyle bir launchpad yok", 404)
        lp = self.calcsheets.exported(user, lp)                 # (its calc sheets go with it: their cells)
        raw = json.dumps(lay.export(lp), ensure_ascii=False, indent=1).encode("utf-8")
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", lp["name"].translate(_ASCII_TR)).strip("-") or "launchpad"
        return raw, "launchpad-%s.json" % safe[:40]

    def import_launchpad(self, user: Optional[str], data: Any, name: Any = None) -> Dict[str, Any]:
        """A launchpad from such a file, added to this user's (a name they have already gets " (2)")."""
        key = self.require_user(user)
        data = self.calcsheets.imported(key, data)              # (its calc sheets: new ones of this user's)
        try:
            lp = lay.imported(data, name if isinstance(name, str) and name.strip() else None)
        except lay.LayoutError as exc:
            raise ServiceError(str(exc))
        with self._layout_lock:
            cur = lay.stored(self.store.get("layout." + key))
            try:
                lp["name"] = lay.unique_name(lp["name"], [x["name"] for x in cur["launchpads"]])
                new = lay.change(cur, {"launchpads": cur["launchpads"] + [lp]})
            except lay.LayoutError as exc:
                raise ServiceError(str(exc))
            self._put_layout(key, new)
        return {"name": lp["name"], "layout": new}

    # ================================================================== RET curve
    def _ret_rows(self, book: Book) -> List[Dict[str, Any]]:
        calc = book.engine.shared
        si = book.model.sheet_index["Forward"]
        rows = []
        for i, tenor in enumerate(RET_TENORS):
            r = RET_FIRST_ROW + i
            rows.append({"tenor": tenor, "days": _to_json(calc.get(si, r, 21)), "bid": _to_json(calc.get(si, r, 23)),
                         "ask": _to_json(calc.get(si, r, 24))})
        return rows

    def ret(self) -> Dict[str, Any]:
        return self.et.call(self._ret)

    def _ret(self) -> Dict[str, Any]:
        book = self._book("tto")
        cells = ["Forward!%s%d" % (col, RET_FIRST_ROW + i) for i in range(len(RET_TENORS)) for col in ("W", "X")]
        return {"rows": self._ret_rows(book), "meta": self.store.shared_meta("tto", cells), "gen": self.gen}

    def set_ret(self, user: str, rows: List[Dict[str, Any]], lang: Optional[str] = None) -> Dict[str, Any]:
        """rows: [{"tenor": "1M", "bid": "34,45", "ask": "34,65"}, ...] - percent or fraction, any separator."""
        user = self.require_user(user)
        items = []
        index = {t: i for i, t in enumerate(RET_TENORS)}
        for row in rows:
            t = str(row.get("tenor", "")).upper().strip().replace("O/N", "ON").replace("T/N", "TN").replace("12M", "1Y")
            if t not in index:
                raise ServiceError("bilinmeyen RET vadesi: %r" % row.get("tenor"))
            r = RET_FIRST_ROW + index[t]
            for col, key in (("W", "bid"), ("X", "ask")):
                if key in row and row[key] not in (None, ""):
                    items.append({"ref": "Forward!%s%d" % (col, r), "value": row[key]})
        if not items:
            raise ServiceError("RET faizi bulunamadı")
        res = self.set_inputs(user, "tto", items, False, lang)
        res["ret"] = self.ret()
        return res

    def ret_history(self) -> List[Dict[str, Any]]:
        return self.store.ret_history(30)

    def ret_meta(self) -> Optional[Dict[str, Any]]:
        """Who loaded the RET curve last, and when (``None``: never - the file's curve is in use)."""
        cells = ["Forward!%s%d" % (col, RET_FIRST_ROW + i) for i in range(len(RET_TENORS)) for col in ("W", "X")]
        return self.store.shared_meta("tto", cells)

    # ================================================================== blotter
    def today_iso(self) -> str:
        return _dt.date.today().isoformat()

    def _sync_blotter(self) -> None:
        book = self.books.get("tto")
        if book is None:
            return
        trades = self.store.trades(self.today_iso())
        book.engine.set_inputs(bl.sheet_values(book, trades))

    def blotter(self, user: Optional[str], date: Optional[str] = None, locale: Optional[str] = None,
                date_to: Optional[str] = None) -> Dict[str, Any]:
        """The trades of a day (today when ``date`` is left out) or, with ``date_to``, of every day from ``date``
        to ``date_to``: a list to look at - trades are entered and deleted on today's page only."""
        return self.et.call(self._blotter, user, date, locale, date_to)

    def _blotter(self, user, date, locale, date_to=None) -> Dict[str, Any]:
        book = self._book("tto")
        today = self.today_iso()
        date = date or today
        date_to = date_to or date
        try:
            d1, d2 = _dt.date.fromisoformat(date), _dt.date.fromisoformat(date_to)
        except ValueError:
            raise ServiceError("tarih anlaşılamadı: %s – %s" % (date, date_to))
        if d2 < d1:
            date, date_to = date_to, date
        ranged = date != date_to
        trades = self.store.trades(date, date_to)
        for t in trades:
            if t.get("kind") == "fwd":
                t["on_rate"] = bl.overnight_equivalent(t.get("try_rate"), t.get("days"))
                if type(t.get("dv01")) is not float:
                    # a trade stored before its DV01 was kept: from its own rates
                    risk = bl.forward_dv01(t.get("dir"), t.get("amount"), t.get("forward"), t.get("days"), t.get("spot"),
                                           None, None, t.get("try_rate"), t.get("usd_rate"))
                    t.update({"dv01_tl": risk["tl"], "dv01": risk["usd"], "usd_dv01": risk["usd_leg"]})
        out: Dict[str, Any] = {"date": date, "to": date_to, "ranged": ranged, "today": today,
                               "is_today": date == today and not ranged, "trades": trades,
                               # a period that runs up to today: what was done in it, and today's entry form too
                               "can_enter": date <= today <= date_to,
                               "cost": bl.summarise(trades), "risk": bl.risk_summary(trades),
                               "dates": self.store.trade_dates(), "gen": self.gen, "tenors": bl.OIS_TENORS}
        loc = numfmt.get_locale(locale or self.settings.locale)
        if ranged:
            out["sheet"] = []                          # the workbook's summary tables belong to a single day
            out["days"] = len({t["trade_date"] for t in trades})
        elif date == today:
            R = self.renderers[book.id]
            calc = book.engine.shared
            sheet_panels = []
            for pid, title, rng in (("fwd", "Forward · vade kovaları (USD karşılığı, TL maliyeti, DV01)", "P1:W20"),
                                    ("ois", "OIS · vade özeti (MPC işlemleri ana vadelere dağıtılmış)", "O22:W39"),
                                    ("bond", "Bonds", "P41:V84"), ("cpt", "OIS — CPT x VADE (DV01 USD)", "P87:V349")):
                try:
                    data = R.table(calc, bl.SHEET, rng, loc, None)
                    _lift_title(data)
                    if pid == "fwd":
                        _add_dv01_columns(data, bl.forward_dv01_buckets(book, calc, trades), loc)
                    sheet_panels.append({"id": pid, "title": title, "range": rng, "data": data})
                except Exception as exc:  # noqa: BLE001
                    sheet_panels.append({"id": pid, "title": title, "error": str(exc)[:200]})
            out["sheet"] = sheet_panels
            # the day's archive: the summary tables as shown and the whole sheet as values (what the workbook's
            # end-of-day macro saved); written only when something changed
            snap = {"sheet": sheet_panels, "cells": self._blotter_cells(book, calc)}
            mark = hash(json.dumps(snap, ensure_ascii=False, sort_keys=True, default=str))
            if self._snapshot_mark.get(date) != mark:
                self.store.save_blotter_snapshot(date, snap)
                self._snapshot_mark = {date: mark}
        else:
            snap = self.store.blotter_snapshot(date)
            out["sheet"] = snap.get("sheet") if snap else []
            out["snapshot_at"] = snap.get("snapshot_at") if snap else None
        return out

    @staticmethod
    def _blotter_cells(book, calc) -> List[List[Any]]:
        """Every non-empty cell of the blotter sheet as [row, column, value]: the sheet "as values"."""
        si = book.model.sheet_index[bl.SHEET]
        sh = book.model.sheets[si]
        out: List[List[Any]] = []
        for r in range(1, sh.max_row + 1):
            for c in range(1, sh.max_col + 1):
                v = calc.get(si, r, c)
                if v is None or v == "":
                    continue
                out.append([r, c, {"e": v.code} if type(v) is XlError else v])
        return out

    def blotter_export(self, user: Optional[str], date: Optional[str] = None,
                       locale: Optional[str] = None, date_to: Optional[str] = None) -> Tuple[bytes, str]:
        """The day's blotter as an .xlsx file (values only) and its file name ``Blotter_yyyy.mm.dd.xlsx``.

        This is the dashboard's version of the workbook's ``GunSonuArsivle`` macro.  Sheet 1 has the blotter
        sheet in Excel's own layout, as values; sheet 2 lists the trades with who entered them and the cost of
        the net positions.  Nothing has to be cleared for the next day: every day has its own list.

        With ``date_to`` the file covers every day from ``date`` to ``date_to``: the list of trades (with their
        day) and the cost of the net positions over the period - the sheet in Excel's layout belongs to one day
        and is left out (``Blotter_yyyy.mm.dd-yyyy.mm.dd.xlsx``).
        """
        return self.et.call(self._blotter_export, user, date, locale, date_to)

    def _blotter_export(self, user, date, locale, date_to=None) -> Tuple[bytes, str]:
        from .xlsx import XlsxBook
        data = self._blotter(user, date, locale, date_to)
        book = self._book("tto")
        si = book.model.sheet_index[bl.SHEET]
        sh = book.model.sheets[si]
        day = _dt.date.fromisoformat(data["date"])
        last = _dt.date.fromisoformat(data["to"])
        ranged = data["ranged"]
        wb = XlsxBook()

        # ---- sheet 1: the blotter sheet as Excel lays it out, values only
        ws = wb.add_sheet(bl.SHEET) if not ranged else None
        cells: List[List[Any]] = []
        if ranged:
            pass
        elif data["is_today"]:
            cells = self._blotter_cells(book, book.engine.shared)
        else:
            snap = self.store.blotter_snapshot(data["date"]) or {}
            cells = snap.get("cells")
            if cells is None:
                # a day archived before whole-sheet snapshots existed: captions, the trades, the saved summaries
                grid: Dict[Tuple[int, int], Any] = {}
                for rc, v in sh.consts.items():
                    grid[divmod(rc, COLS)] = v
                for (_, rc), v in bl.sheet_values(book, data["trades"]).items():
                    if v is None:
                        grid.pop(divmod(rc, COLS), None)
                    else:
                        grid[divmod(rc, COLS)] = v
                for panel in snap.get("sheet") or []:
                    t = panel.get("data") or {}
                    sheet_cols = len(t.get("c") or []) - int(t.get("added") or 0)   # the dashboard's own columns are no cells
                    for i, row in enumerate(t.get("rows") or []):
                        for j, cell in enumerate(row):
                            if cell.get("sk") or j >= sheet_cols:
                                continue
                            r, c = t["r"][i], parse_a1("%s1" % t["c"][j]) % COLS
                            if "v" in cell:
                                grid[(r, c)] = cell["v"]
                            elif cell.get("t"):
                                grid[(r, c)] = cell["t"]
                cells = [[r, c, v] for (r, c), v in sorted(grid.items())]
        for r, c, v in cells:
            if isinstance(v, dict):
                v = XlError(v.get("e", "#N/A"))
            elif isinstance(v, int) and not isinstance(v, bool):
                v = float(v)
            # rows the workbook left empty carry no format of their own: a list row looks like the list's first row
            xf_i = sh.styles.get(r * COLS + c) or (sh.styles.get(3 * COLS + c, 0) if r > 3 else 0)
            xf = book.model.xfs[xf_i] if xf_i < len(book.model.xfs) else book.model.xfs[0]
            ws.set(r, c, v, fmt=xf[0], bold=bool(xf[1]), align=xf[4] if xf[4] in ("left", "center", "right") else None)
        if ws is not None:
            ws.widths = {c: w for c, w in sh.col_widths.items() if c <= sh.max_col}
            ws.merges = [m for m in sh.merges]
            ws.freeze = (sh.freeze[0], sh.freeze[1]) if len(sh.freeze) > 1 else (0, 0)

        # ---- sheet 2: the trades as entered, and the cost of the net positions
        ls = wb.add_sheet("İşlem listesi")
        names = {u["name"]: u["display"] for u in self.store.users()}
        who = lambda t: names.get(t.get("created_by"), t.get("created_by") or "")          # noqa: E731
        clock = lambda t: (t.get("created_at") or "")[11:19]                                 # noqa: E731
        basis = {"RET_BID": "RET bid", "RET_MID": "RET mid", "RET_ASK": "RET ask", "TRY": "TRY faizi", "FWD": "Forward kur",
                 "SP": "Swap puanı"}
        role = {"outright": "Outright", "short": "Kısa", "long": "Uzun", "wing1": "Kanat 1", "body": "Gövde",
                "wing2": "Kanat 2", "start": "Başlangıç", "end": "Bitiş"}
        INT, AMT, FX, P3, P4, BP, DATE = "#,##0", "#,##0.00", "#,##0.0000", "0.000%", "0.0000%", "#,##0.00", "dd.mm.yyyy"
        period = day.strftime("%d.%m.%Y") if not ranged else "%s – %s" % (day.strftime("%d.%m.%Y"), last.strftime("%d.%m.%Y"))
        ls.set(1, 1, "Günlük İşlemler · %s" % period, bold=True)
        ls.set(2, 1, "Dışa aktarım: %s%s" % (_dt.datetime.now().strftime("%d.%m.%Y %H:%M"),
                                              " · %s" % names.get(user, user) if user else ""))
        row = 4

        def table(title: str, header: List[str], rows: List[List[Any]], fmts: List[Optional[str]]) -> None:
            nonlocal row
            ls.set(row, 1, title, bold=True)
            row += 1
            ls.row(row, 1, header, bold=True, fill="E7E6E6")
            row += 1
            if not rows:
                ls.set(row, 1, "kayıt yok")
                row += 1
            for line in rows:
                for k, v in enumerate(line):
                    ls.set(row, 1 + k, float(v) if isinstance(v, int) and not isinstance(v, bool) else v, fmt=fmts[k])
                row += 1
            row += 1

        # a period: every row starts with its day (the file of a single day keeps the columns it always had)
        lead = ["Tarih"] if ranged else []
        lead_fmt: List[Optional[str]] = [DATE] if ranged else []

        def when(t: Dict[str, Any]) -> List[Any]:
            return [date_to_serial(_dt.date.fromisoformat(t["trade_date"]))] if ranged else []

        trades = data["trades"]
        fw = [t for t in trades if t["kind"] == "fwd"]
        # the pair comes last: the columns before it are where they were when every forward was USDTRY
        table("Forward", lead + ["Saat", "Kullanıcı", "Yön", "Tutar (döviz)", "Valör", "Gün", "TRY faizi", "Forward", "TL tutarı",
                                 "Fiyatlama", "Karşı taraf", "Not", "O/N karşılığı", "DV01 (TL)", "DV01 ($)", "Parite", "Swap puanı"],
              [when(t) + [clock(t), who(t), "ALIŞ" if t["dir"] == "B" else "SATIŞ", t.get("amount"), t.get("value_date"), t.get("days"),
                          t.get("try_rate"), t.get("forward"), t.get("tl"), basis.get(t.get("basis"), t.get("basis") or ""),
                          t.get("cpt") or "", t.get("note") or "", t.get("on_rate"), t.get("dv01_tl"), t.get("dv01"),
                          t.get("pair") or "USDTRY", t.get("points")] for t in fw],
              lead_fmt + [None, None, None, INT, DATE, INT, P3, FX, AMT, None, None, None, P3, INT, INT, None, INT])
        seen = set()
        ois_rows = []
        for t in (x for x in trades if x["kind"] == "ois"):
            first = not t.get("package") or t["package"] not in seen
            if t.get("package"):
                seen.add(t["package"])
            ois_rows.append(when(t) + [clock(t), who(t), t.get("label") or "", role.get(t.get("role"), t.get("role") or ""),
                                       "RECEIVE" if t["dir"] == "S" else "PAY", t.get("tenor"), t.get("rate"), t.get("nominal"),
                                       _payer_plus(t),
                                       t.get("cost_bp") if first else None, t.get("cost_usd") if first else None, t.get("cpt") or "",
                                       t.get("note") or ""])
        table("OIS", lead + ["Saat", "Kullanıcı", "İşlem", "Bacak", "Yön", "Vade", "Oran", "Nominal (TL)", "DV01 ($)", "Maliyet (bp)",
                             "Maliyet ($)", "Karşı taraf", "Not"], ois_rows,
              lead_fmt + [None, None, None, None, None, None, P4, INT, INT, BP, INT, None, None])
        bd = [t for t in trades if t["kind"] == "bond"]
        table("Tahvil", lead + ["Saat", "Kullanıcı", "Enstrüman", "Yön", "Tutar", "Fiyat", "Not", "DV01 (TL)", "DV01 ($)"],
              [when(t) + [clock(t), who(t), t.get("instrument"), "ALIŞ" if t["amount"] >= 0 else "SATIŞ", abs(t["amount"]), t.get("price"),
                          t.get("note") or "", t.get("dv01_tl"), t.get("dv01")] for t in bd],
              lead_fmt + [None, None, None, None, INT, FX, None, INT, INT])
        cost = data.get("cost") or {"fwd": [], "ois": [], "bond": []}
        table("Forward · pozisyon ve maliyet", ["Valör", "Alış (döviz)", "Ort. alış kuru", "Satış (döviz)", "Ort. satış kuru", "Net (döviz)",
                                                 "Maliyet (kur)", "Gerçekleşen K/Z (TL)", "Parite"],
              [[x["key"], x["buy"], x["buy_avg"], x["sell"], x["sell_avg"], x["net"], x["cost"], x["realised"], x.get("pair") or "USDTRY"]
               for x in cost["fwd"]],
              [DATE, INT, FX, INT, FX, INT, FX, AMT, None])
        table("OIS · pozisyon ve maliyet", ["Vade", "Pay DV01 ($)", "Ort. pay", "Receive DV01 ($)", "Ort. receive", "Net DV01 ($)",
                                             "Maliyet", "Gerçekleşen K/Z ($)"],
              [[x["key"], x["buy"], x["buy_avg"], x["sell"], x["sell_avg"], x["net"], x["cost"], x["realised"]] for x in cost["ois"]],
              [None, INT, P4, INT, P4, INT, P4, INT])
        table("Tahvil · pozisyon ve maliyet", ["Enstrüman", "Alış", "Ort. alış", "Satış", "Ort. satış", "Net", "Maliyet",
                                                "Gerçekleşen K/Z"],
              [[x["key"], x["buy"], x["buy_avg"], x["sell"], x["sell_avg"], x["net"], x["cost"], x["realised"]] for x in cost["bond"]],
              [None, INT, FX, INT, FX, INT, FX, AMT])
        risk = data.get("risk") or {}
        table("DV01 özeti · TRY faizi +1 bp ($; payer + : faiz artınca kazanır)", ["Forward", "OIS (net)", "Tahvil", "Toplam", "DV01'i bilinmeyen işlem"],
              [[risk.get("fwd"), risk.get("ois"), risk.get("bond"), risk.get("total"), risk.get("unknown")]], [INT, INT, INT, INT, INT])
        ls.autosize()
        name = "Blotter_%s.xlsx" % day.strftime("%Y.%m.%d") if not ranged else \
            "Blotter_%s-%s.xlsx" % (day.strftime("%Y.%m.%d"), last.strftime("%Y.%m.%d"))
        return wb.to_bytes(), name

    @staticmethod
    def _own_spot(code: str) -> bool:
        """Whether a pair has a spot date of its own, apart from the Forward sheet's: a pair of two currencies the desk
        keeps holiday lists of that is neither USDTRY nor EURTRY (EURUSD)."""
        return bool(ex.pair_calendar(code)) and code not in ("USDTRY", "EURTRY")

    def _pair_spot(self, code: str) -> Optional[float]:
        """The spot date (serial) a value date of the pair counts from.  USDTRY's and EURTRY's are the Forward sheet's
        (I2, K2: from the desk's lists, or the date typed there); EURUSD's is its own - two days after today that are
        business days of both USD and EUR, as K2 counts EURTRY's, a TRY holiday not among them; any other pair counts
        from USDTRY's (one starting with EUR from EURTRY's), as before.  On the calculation thread."""
        from .fx import SPOT_LAG, add_week_days
        book = self.books.get("tto")
        if book is None:
            return None
        if self._own_spot(code):
            holidays = {serial_to_date(s) for s in self._calendar_serials(ex.pair_calendar(code))}
            day = add_week_days(serial_to_date(book.engine.clock.today()), SPOT_LAG.get(code, 2), holidays)
            return float(date_to_serial(day))
        si, rc = book.cell("Forward!K2" if code.startswith("EUR") else "Forward!I2")
        spot = book.engine.shared.get(si, *divmod(rc, COLS))
        if isinstance(spot, str):
            spot = parse_date(spot)
        return spot if type(spot) is float else None

    def _tenor_date(self, text: str, pair: str = "USDTRY") -> Optional[float]:
        """The value date of a tenor ("2W", "3M", "1Y") from the pair's spot date (:meth:`_pair_spot`): n weeks, or n
        months and then the next business day of the pair's calendar - the holidays of both its currencies (USDTRY: TRY
        and USD, EURTRY: TRY and EUR, EURUSD: USD and EUR; any other pair the TRY list, as before) - as the Forward sheet
        dates its tenors."""
        m = re.match(r"^\s*(\d{1,3})\s*([WMYwmy])\s*$", str(text or ""))
        book = self.books.get("tto")
        if m is None or book is None:
            return None
        try:
            code = bl.pair_of(pair)
        except bl.TradeError:
            code = "USDTRY"
        spot = self._pair_spot(code)
        if type(spot) is not float:
            return None
        holidays = self._calendar_serials(ex.pair_calendar(code) or ("TRY",))
        n, unit = int(m.group(1)), m.group(2).upper()
        start = serial_to_date(spot)
        if unit == "W":
            day = start + _dt.timedelta(days=7 * n)
        else:
            months = n * (12 if unit == "Y" else 1)
            y, mo = divmod(start.month - 1 + months, 12)
            y, mo = start.year + y, mo + 1
            last = (_dt.date(y + (mo == 12), mo % 12 + 1, 1) - _dt.timedelta(days=1)).day
            day = _dt.date(y, mo, min(start.day, last))
        while day.weekday() >= 5 or date_to_serial(day) in holidays:
            day += _dt.timedelta(days=1)
        return float(date_to_serial(day))

    def quote_forward(self, user: Optional[str], payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        return self.et.call(self._quote_forward, user, payload, lang)

    def _fwd_payload(self, payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        lang = lang or self.settings.locale
        p = dict(payload)
        vd = p.get("value_date")
        if isinstance(vd, str):
            d = parse_date(vd)
            if d is None:
                d = self._tenor_date(vd, str(p.get("pair") or "USDTRY"))          # "3M", "2W", "1Y": from the pair's spot
            if d is None:
                raise ServiceError("valör tarihi anlaşılamadı: %r (örn. 15.12.2026 ya da 3M)" % vd)
            p["value_date"] = d
        elif isinstance(vd, (int, float)):
            p["value_date"] = float(vd)
        amt = p.get("amount")
        if isinstance(amt, str):
            n = parse_amount(amt, lang)
            p["amount"] = n
        elif isinstance(amt, (int, float)):
            p["amount"] = float(amt)
        man = p.get("manual")
        basis = str(p.get("basis", "RET_MID")).upper()
        if isinstance(man, str):
            # swap points are thousands ("14.200" in Turkish format); a rate or an outright is a decimal
            n = parse_number(man, lang, prefer_decimal=basis != "SP")
            if n is not None and basis == "TRY" and not (man.strip().endswith("%") or man.strip().startswith("%")) and abs(n) >= 1.0:
                n /= 100.0
            p["manual"] = n
        elif isinstance(man, (int, float)):
            p["manual"] = float(man)
        spot = p.get("spot")
        if isinstance(spot, str):
            p["spot"] = parse_number(spot, lang, prefer_decimal=True)
        elif isinstance(spot, bool) or not isinstance(spot, (int, float)):
            p["spot"] = None
        else:
            p["spot"] = float(spot)
        try:
            p["pair"] = bl.pair_of(p.get("pair"))
        except bl.TradeError as exc:
            raise ServiceError(str(exc))
        # a pair with a spot date of its own (EURUSD): its days count from that, not from the USDTRY sheet's
        p["spot_date"] = self._pair_spot(p["pair"]) if self._own_spot(p["pair"]) else None
        return p

    def _quote_forward(self, user, payload, lang=None) -> Dict[str, Any]:
        book = self._book("tto")
        p = self._fwd_payload(payload, lang)
        if type(p.get("value_date")) is not float:
            raise ServiceError("valör tarihi gerekli")
        ov = self._overlay(user_key(user), book) if user else {}
        try:
            q = bl.price_forward(book, ov, p["value_date"], str(p.get("basis", "RET_MID")).upper(),
                                 p.get("manual") if type(p.get("manual")) is float else None, p["pair"],
                                 p.get("spot") if type(p.get("spot")) is float else None, p["spot_date"])
        except bl.TradeError as exc:
            raise ServiceError(str(exc))
        amount = p.get("amount")
        direction = "S" if str(p.get("dir", "B")).upper() == "S" else "B"
        if type(amount) is float and amount > 0:
            q["amount"] = amount
            q["tl"] = amount * q["forward"]
        size = amount if type(amount) is float and amount > 0 else 1e6           # no amount yet: per 1 mn of the currency
        q["dv01"] = bl.forward_dv01(direction, size, q["forward"], q["days"], q.get("usdtry"), q.get("df_try"), q.get("df_usd"),
                                    q["try_rate"] if q["quote"] == "TRY" else None, q.get("usd_rate"))
        q["dv01"]["amount"] = size
        q["dv01"]["dir"] = direction
        q["value_date_iso"] = serial_to_date(q["value_date"]).isoformat()
        return q

    def add_forward(self, user: str, payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        user = self.require_user(user)
        res = self.et.call_at(EngineThread.WRITE, self._add_forward, user, payload, lang)
        self.bump()
        return res

    def _add_forward(self, user, payload, lang=None) -> Dict[str, Any]:
        book = self._book("tto")
        try:
            rec = bl.forward_trade(book, self._overlay(user, book), self._fwd_payload(payload, lang))
        except bl.TradeError as exc:
            raise ServiceError(str(exc))
        tid = self.store.add_trade(self.today_iso(), "fwd", rec, user)
        self._sync_blotter()
        rec["id"] = tid
        return rec

    def _ois_payload(self, payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        lang = lang or self.settings.locale
        p = dict(payload)
        p["_lang"] = lang
        strategy = str(p.get("strategy", "outright")).lower()
        for k in ("start", "end"):
            v = p.get(k)
            if isinstance(v, str):
                p[k] = parse_date(v)
                if p[k] is None and v.strip():
                    raise ServiceError("tarih anlaşılamadı: %r" % v)
            elif isinstance(v, bool) or not isinstance(v, (int, float)):
                p[k] = None
            else:
                p[k] = float(v)
        for k in ("level", "dv01", "nominal", "short_rate", "wing1_rate", "wing2_rate", "start_rate",
                  "start_months", "end_months"):
            v = p.get(k)
            if isinstance(v, str):
                rate_like = k in ("short_rate", "wing1_rate", "wing2_rate", "start_rate") or \
                    (k == "level" and strategy in ("outright", "fra", "mpc"))
                n = parse_amount(v, lang) if k in ("dv01", "nominal") else parse_number(v, lang, prefer_decimal=True)
                if n is not None and rate_like and not ("%" in v) and abs(n) >= 1.0:
                    n /= 100.0                    # 35,5 typed for 35,5 %
                p[k] = n
            elif isinstance(v, bool):
                p[k] = None
            elif isinstance(v, (int, float)):
                x = float(v)
                if k == "level" and strategy in ("outright", "fra", "mpc") and abs(x) >= 1.0:
                    x /= 100.0
                p[k] = x
        return p

    def quote_ois(self, user: Optional[str], payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        return self.et.call(self._quote_ois, user, payload, lang)

    def _quote_ois(self, user, payload, lang=None) -> Dict[str, Any]:
        book = self._book("tto")
        try:
            return bl.ois_legs(self._ois_curve(user_key(user) if user else None, book), self._ois_payload(payload, lang))
        except bl.TradeError as exc:
            raise ServiceError(str(exc))

    def _ois_curve(self, user: Optional[str], book: Book) -> "bl.OisMarket":
        """The TRY OIS curve as the user sees it (``user``: a user key, or nobody)."""
        return bl.OisMarket(book, self._calc(user, book), self._overlay(user, book) if user else None)

    def ois_market(self, user: Optional[str]) -> Dict[str, Any]:
        """Mid par rates / annuities per tenor for the trade form."""
        return self.et.call(self._ois_market, user)

    def _ois_market(self, user) -> Dict[str, Any]:
        book = self._book("tto")
        mkt = self._ois_curve(user_key(user) if user else None, book)
        rows = []
        for t in bl.OIS_TENORS:
            try:
                rows.append({"tenor": t, "par": mkt.par(t), "annuity": mkt.annuity(t)})
            except bl.TradeError:
                rows.append({"tenor": t, "par": mkt.par(t), "annuity": None})
        out = {"tenors": rows, "gen": self.gen}
        # the dates a meeting-dated swap can run between: OIS spot and the day after every coming decision
        mpc = mkt.mpc_dates()
        text = lambda d: serial_to_date(d).strftime("%d.%m.%Y")      # noqa: E731
        out["mpc"] = {"spot": mpc["spot"], "spot_text": text(mpc["spot"]) if mpc["spot"] else None,
                      "dates": [{"k": k + 1, "date": d, "text": text(d),
                                 "market": mpc["market"][k] if k < len(mpc["market"]) else None}
                                for k, d in enumerate(mpc["dates"])]}
        try:
            out.update({"usdtry": mkt.usdtry, "lot": mkt.lot, "dv01": mkt.default_dv01})
        except bl.TradeError:
            pass
        return out

    def add_ois(self, user: str, payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        user = self.require_user(user)
        res = self.et.call_at(EngineThread.WRITE, self._add_ois, user, payload, lang)
        self.bump()
        return res

    def _add_ois(self, user, payload, lang=None) -> Dict[str, Any]:
        book = self._book("tto")
        try:
            q = bl.ois_legs(self._ois_curve(user, book), self._ois_payload(payload, lang))
        except bl.TradeError as exc:
            raise ServiceError(str(exc))
        package = uuid.uuid4().hex[:12] if len(q["legs"]) > 1 else None
        recs = []
        for lg in q["legs"]:
            rec = {"dir": lg["dir"], "tenor": lg["tenor"], "rate": lg["rate"], "dv01": lg["dv01"],
                   "nominal": lg["nominal"], "cpt": lg["cpt"], "role": lg["role"], "strategy": q["strategy"],
                   "label": q["label"], "level": q["level"], "side": q["side"],
                   "cost_bp": q["info"].get("cost_bp"), "cost_usd": q["info"].get("cost_usd"),
                   "market": q["info"].get("market"), "note": str(payload.get("note") or "").strip()[:200]}
            if lg.get("mpc"):
                rec["mpc"] = lg["mpc"]
            recs.append(rec)
        ids = self.store.add_trades(self.today_iso(), "ois", recs, user, package)     # every leg, or none
        self._sync_blotter()
        q["ids"] = ids
        return q

    def _bond_payload(self, payload: Dict[str, Any], lang: Optional[str]) -> Tuple[str, Optional[float], Optional[float]]:
        lang = lang or self.settings.locale
        inst = str(payload.get("instrument") or "").strip()[:60]
        amount = payload.get("amount")
        amount = parse_amount(amount, lang) if isinstance(amount, str) else (float(amount) if isinstance(amount, (int, float)) else None)
        price = payload.get("price")
        price = parse_number(price, lang, prefer_decimal=True) if isinstance(price, str) else (float(price) if isinstance(price, (int, float)) else None)
        side = str(payload.get("dir") or "").upper()
        if amount is not None:
            if side == "S":
                amount = -abs(amount)
            elif side == "B":
                amount = abs(amount)
        return inst, amount, price

    def _bond_risk(self, user: Optional[str], inst: str, amount: Optional[float]) -> Dict[str, Any]:
        """What the DİBS RV table says about the bond, and the DV01 of ``amount`` nominal of it."""
        book = self._book("tto")
        calc = self._calc(user_key(user) if user else None, book)
        info = bl.bond_info(book, calc, inst)
        try:
            usdtry = bl.OisMarket(book, calc).usdtry
        except bl.TradeError:
            usdtry = None
        size = amount if amount else 1e6
        risk = bl.bond_dv01(size, info, usdtry)
        return {"instrument": inst, "known": info is not None, "info": info, "usdtry": usdtry,
                "amount": amount, "per": size, "dv01_tl": risk["tl"], "dv01": risk["usd"]}

    def quote_bond(self, user: Optional[str], payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        """Name, price in use, duration and DV01 of the bond being typed (when the DİBS RV table lists it)."""
        inst, amount, _ = self._bond_payload(payload, lang)
        if not inst:
            raise ServiceError("enstrüman gerekli")
        return self.et.call(self._bond_risk, user, inst, amount)

    def add_bond(self, user: str, payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        user = self.require_user(user)
        inst, amount, price = self._bond_payload(payload, lang)
        if not inst:
            raise ServiceError("enstrüman gerekli")
        if amount is None or amount == 0:
            raise ServiceError("tutar gerekli (+ alış / − satış)")
        if price is None or price <= 0:
            raise ServiceError("fiyat gerekli")
        rec = {"instrument": inst, "amount": amount, "price": price, "note": str(payload.get("note") or "").strip()[:200]}
        risk = self.et.call(self._bond_risk, user, inst, amount)
        rec.update({"dv01_tl": risk["dv01_tl"], "dv01": risk["dv01"],
                    "name": (risk["info"] or {}).get("name") if risk["known"] else None})
        tid = self.store.add_trade(self.today_iso(), "bond", rec, user)
        self.et.call_at(EngineThread.WRITE, self._sync_blotter)
        self.bump()
        rec["id"] = tid
        return rec

    # ================================================================== what Bloomberg does not know
    #: what a ticker of a known shape is, when Bloomberg does not know it
    _UNKNOWN_NOTES = (
        (re.compile(r"^TYB\d+D BFX\d", re.I),
         "BIST swap vadesi: Borsa Swap çalışma kitabı 1–400 günün her birini iki valörde (BFX0 = T+0, BFX1 = T+1) sorar; "
         "Bloomberg'de yalnızca tanımlı vadeler vardır. Beklenen, zararsız: o vadeler tabloda boş kalır."),
        (re.compile(r"^(@\S+\s+)?(Corp|Govt|Mtge|Muni|Pfd)$", re.I),
         "Kod boş: tablonun bu satırında ISIN yazılı değil, ticker yalnızca fiyat kaynağı ve sınıftan oluşuyor. Satır boşsa zararsız."),
        (re.compile(r"^\S+@\S+\s+(ISIN|CUSIP|SEDOL)$|^/isin/\S+@", re.I),
         "Fiyat kaynaklı ISIN: Bloomberg bu tahvili bu kaynakta (@...) tanımıyor; ISIN ya da kaynak yanlış olabilir."),
        (re.compile(r"\b(Curncy|Index|Corp|Govt|Comdty|Equity)\s+\1$", re.I),
         "Sarı anahtar iki kez yazılmış: hücrede tam ticker var, formül bir tane daha ekliyor (VİOP!B58:B69 – C sütunundaki ICAP ticker'ına "
         "\" Curncy\" ekleyip vade gününü soruyor). O sütun boş kalır; zararsız, Excel'de düzeltilebilir."),
        (re.compile(r"^\s|\s\s|^\S+$"), "Ticker'ın yazımı eksik (boşluk ya da sarı anahtar – Curncy, Index, Corp, Comdty … – yok)."),
    )
    _SOURCE_NOTE = ("Ayarlar → Veri kaynakları listesindeki bir kaynak bu vadeyi yayınlamıyor: sıradaki kaynak (en sonda Excel'deki BGN "
                    "ticker'ı) kullanılır – zararsız. Bu kaynağı hiç kullanmayacaksanız listeden çıkarın.")
    _ANSWERS = {INVALID_SECURITY: ("security", "Bloomberg'de böyle bir menkul kıymet yok (Invalid Security)"),
                INVALID_FIELD: ("field", "Alan yok (Invalid Field)"),
                NOT_APPLICABLE: ("na", "Alan bu menkul kıymet için geçerli değil (Field Not Applicable)")}

    def _cell_places(self) -> Dict[Tuple[str, str], List[Tuple[int, int, int, int, str, str]]]:
        """(book, sheet) -> the tables of the pages that show it: (r1, c1, r2, c2, page, panel)."""
        hit = getattr(self, "_places", None)
        if hit is not None:
            return hit
        out: Dict[Tuple[str, str], List[Tuple[int, int, int, int, str, str]]] = {}
        for v in self.views:
            for p in v["panels"]:
                if p.get("type", "table") != "table" or not p.get("range"):
                    continue
                try:
                    r1, c1, r2, c2 = parse_range(p["range"])
                except Exception:  # noqa: BLE001
                    continue
                out.setdefault((v["book"], p.get("sheet") or v.get("sheet")), []).append((r1, c1, r2, c2, v["id"], p["id"]))
        self._places = out
        return out

    def _market_callers(self) -> Dict[Tuple, List[Tuple[str, int, int]]]:
        """Which cell asks for which market-data item, in every workbook (cached until an input changes)."""
        mark = self.gen
        hit = getattr(self, "_callers_cache", None)
        if hit is not None and hit[0] == mark:
            return hit[1]
        from .marketdata.replay import addin_callers

        def scan() -> Dict[Tuple, List[Tuple[str, int, int]]]:
            out: Dict[Tuple, List[Tuple[str, int, int]]] = {}
            for bid, book in self.books.items():
                for key, cells in addin_callers(book.engine).items():
                    out.setdefault(key, []).extend((bid, si, rc) for si, rc in cells)
            return out

        found = self.et.call(scan)
        self._callers_cache = (mark, found)
        return found

    # ================================================================== bond lists
    #: the lists of bonds on the pages, by page: (book, the cells of the list)
    BOND_LISTS = {"dibs": ("tto", "DİBS RV!A5:A54"), "asw": ("asw", "ASW!B7:B56"), "bulk": ("tto", "Bulk Bond!A3:A52")}

    def bond_catalog(self, user: Optional[str] = None) -> Dict[str, Any]:
        """The TRY government bonds of the desk's list (Tüm Kâğıtlar), each with the lists it is already in."""
        lists = {name: self._list_values(user, *where) for name, where in self.BOND_LISTS.items() if where[0] in self.books}
        rows = []
        for b in bd.listed(self._bond_day()):
            rows.append(dict(b, label=bd.short_label(b), kind_text=bd.KINDS.get(b.get("kind"), b.get("kind") or ""),
                             lists=[name for name, vals in lists.items() if b["isin"] in vals]))
        return {"bonds": rows, "kinds": bd.KINDS, "lists": {k: len([v for v in vals if v]) for k, vals in lists.items()}}

    def _list_values(self, user: Optional[str], book_id: str, ref: str) -> List[str]:
        book = self.books[book_id]

        def run():
            calc = self._calc(user_key(user) if user else None, book)
            return ["".join(str(v).split()).upper() if isinstance(v, str) else ""
                    for v in (calc.get(si, *divmod(rc, COLS)) for si, rc in book.cells_of(ref))]

        return self.et.call(run)

    @staticmethod
    def _isins(values: List[Any]) -> List[str]:
        """The ISINs typed / pasted / picked (spaces, commas, lines between), each once; an error names the ones whose
        check digit is wrong."""
        wanted: List[str] = []
        bad: List[str] = []
        for v in values or []:
            for code in re.split(r"[\s,;]+", str(v or "")):
                code = code.strip().upper()
                if not code:
                    continue
                if not bd.isin_valid(code):
                    bad.append(code)
                elif code not in wanted:
                    wanted.append(code)
        if bad:
            raise ServiceError("ISIN değil ya da kontrol hanesi tutmuyor: " + ", ".join(bad[:8]))
        return wanted

    def list_add(self, user: str, book_id: str, ref: str, values: List[Any]) -> Dict[str, Any]:
        """Bonds added to a list of a page by ISIN: below its last bond (then into the empty rows between, when the
        end is full), for everyone when the list is a shared one, each ISIN once.  An ISIN whose check digit is
        wrong is refused; one already listed is skipped."""
        user = self.require_user(user)
        book = self._book(book_id)
        try:
            cells = book.cells_of(ref)
        except (KeyError, ValueError):
            raise ServiceError("liste bulunamadı: %s" % ref, 404)
        if not all(c in book.inputs for c in cells):
            raise ServiceError("bu hücreler bir liste değil: %s" % ref)
        current = self._list_values(user, book_id, ref)
        wanted = self._isins(values)
        skipped = [c for c in wanted if c in current]
        todo = [c for c in wanted if c not in current]
        # below the last bond of the list first: the empty rows the desk keeps between its groups stay empty
        # until there is no room left at the end
        last = max([k for k, v in enumerate(current) if v] or [-1])
        free = [k for k, v in enumerate(current) if not v and k > last] + [k for k, v in enumerate(current) if not v and k < last]
        if len(todo) > len(free):
            raise ServiceError("listede %d boş satır var, %d kâğıt eklenmek istendi" % (len(free), len(todo)))
        items = [{"ref": book.ref(*cells[k]), "value": code} for k, code in zip(free, todo)]
        res = self.set_inputs(user, book_id, items) if items else {"applied": 0, "errors": []}
        if res["errors"]:
            raise ServiceError("; ".join(res["errors"]))
        return {"added": todo, "skipped": skipped, "cells": [i["ref"] for i in items], "free": len(free) - len(todo), "gen": self.gen}

    #: the trading list: the bonds of DİBS RV (and so of DİBS Trading)
    TRADING_LIST = ("tto", "DİBS RV!A5:A54")
    #: what goes with a bond's row of the trading list and is cleared when the bond leaves it: its source
    #: (the desk's) and each user's known coupon, manual clean price and repo
    _ROW_SHARED, _ROW_PERSONAL = ("B",), ("H", "N", "AL")
    #: the ASW workbook's list of bonds (its curve and charts) follows the trading list: ★ / ☆ there too.  What goes
    #: with its row: the source (the desk's), each user's manual clean price and curve flag
    ASW_LIST = ("asw", "ASW!B7:B56")
    _ASW_ROW_SHARED, _ASW_ROW_PERSONAL = ("C",), ("D", "E")

    def _list_off(self, user: str, book_id: str, ref: str, code: str, shared: Tuple[str, ...], personal: Tuple[str, ...]) -> int:
        """A bond off a list of bonds: its rows empty, with what goes with them (``shared``: the desk's columns,
        ``personal``: every user's).  Returns the rows emptied."""
        book = self._book(book_id)
        cells = book.cells_of(ref)
        current = self._list_values(user, book_id, ref)
        rows = [cells[k][1] // COLS for k, v in enumerate(current) if v == code]
        if not rows:
            return 0
        sheet = ref.split("!")[0]
        col = re.match(r"[A-Z]+", ref.split("!")[1]).group(0)
        items = [{"ref": "%s!%s%d" % (sheet, c, r), "value": None} for r in rows for c in (col,) + shared]
        res = self.set_inputs(user, book_id, items)
        if res["errors"]:
            raise ServiceError("; ".join(res["errors"]))
        self.et.call_at(EngineThread.WRITE, self._clear_rows_for_everyone, book, ["%s!%s%d" % (sheet, c, r) for r in rows for c in personal])
        return len(rows)

    def _asw_follows(self, user: str, code: str, on: bool) -> Optional[bool]:
        """The ASW workbook's list with the trading list: the bond added (``on``) or taken off there too.  ``None``: no
        ASW list here; False: nothing to do (already listed / not listed, or no room left - the trading list still
        takes it)."""
        book_id, ref = self.ASW_LIST
        book = self.books.get(book_id)
        try:
            if book is None or not all(c in book.inputs for c in book.cells_of(ref)):
                return None
        except (KeyError, ValueError):
            return None
        if on:
            try:
                return bool(self.list_add(user, book_id, ref, [code])["added"])
            except ServiceError:
                return False
        return self._list_off(user, book_id, ref, code, self._ASW_ROW_SHARED, self._ASW_ROW_PERSONAL) > 0

    def bond_flag(self, user: str, isin: str, on: bool) -> Dict[str, Any]:
        """★ a bond: onto the trading list (below its last bond) or off it - for everyone.  A bond taken off leaves
        its row empty, with nothing of it left behind (its source, everyone's manual price, coupon, repo)."""
        from . import bonds as bd
        user = self.require_user(user)
        code = "".join(str(isin or "").split()).upper()
        if not bd.isin_valid(code):
            raise ServiceError("ISIN değil ya da kontrol hanesi tutmuyor: %s" % (code or "(boş)"))
        book_id, ref = self.TRADING_LIST
        if on:
            res = self.list_add(user, book_id, ref, [code])
            asw = self._asw_follows(user, code, True)
            return {"isin": code, "on": True, "added": bool(res["added"]), "cells": res["cells"], "asw": asw, "gen": self.gen}
        removed = self._list_off(user, book_id, ref, code, self._ROW_SHARED, self._ROW_PERSONAL)
        asw = self._asw_follows(user, code, False)
        self.bump()
        return {"isin": code, "on": False, "removed": removed, "asw": asw, "gen": self.gen}

    def _clear_rows_for_everyone(self, book, refs: List[str]) -> None:
        """Every user's personal values of these cells: gone (the bond they were for left its row)."""
        keys = []
        for ref in refs:
            try:
                keys.append(book.cell(ref))
            except (KeyError, ValueError):
                continue
        for row in self.store.users():
            name = row["name"]
            self.store.clear_user_inputs(name, book.id, [book.ref(si, rc) for si, rc in keys])
            ov = self._overlays.get((name, book.id))
            if ov and any(k in ov for k in keys):
                ov = {k: v for k, v in ov.items() if k not in keys}
                self._overlays[(name, book.id)] = ov
                book.engine.set_user_inputs(name, ov)
        self._note_private()

    def _flag_cell(self, isin: str, listed: bool) -> Dict[str, Any]:
        return {"t": "★" if listed else "☆", "k": "s", "cls": "act flag" + (" on" if listed else ""),
                "tip": ("Trading listesinden çıkar: " if listed else "Trading listesine ekle (DİBS RV, DİBS Trading): ") + isin}

    # ================================================================== Tüm Kâğıtlar: the desk's list of bonds
    #: the store's key of the desk's changes to the list: bonds added ``{isin: bond + by / at}`` (a bond whose kind
    #: Bloomberg has not told yet has ``kind`` None), taken off ``{isin: {by, at}}``, refused ``{isin: {why, by, at}}``
    BOND_DESK = "bonds.desk"
    #: Tüm Kâğıtlar's old rows of the bonds the desk typed in (before the list was the desk's), moved onto the list
    _OWN_ROWS = (ex.UNI_SHEET, 6, 20)
    BOND_WAIT = 4.0          # seconds a bond added waits for Bloomberg to say what it is (then: its kind comes later)
    BOND_RETRY = 10.0        # how often the kinds Bloomberg has not told yet are asked again
    _REFUSED = {"unknown": "Bloomberg bu ISIN'i tanımıyor", "kind": "türü desteklenmiyor (kupon tipi)",
                "matured": "vadesi geçmiş", "full": "liste dolu (%d kâğıt)" % ex.UNI_ROWS}

    def _refusal(self, why: str) -> str:
        if why.startswith("fx:"):
            return "%s cinsi: döviz cinsi kâğıt listeye alınmaz" % why[3:]
        return self._REFUSED.get(why, why)

    def _desk_now(self) -> Dict[str, Dict[str, Any]]:
        desk = self.store.get(self.BOND_DESK) or {}
        return {k: dict(desk.get(k) or {}) for k in ("added", "removed", "refused")}

    def _save_desk(self, desk: Dict[str, Dict[str, Any]]) -> None:
        self.store.put(self.BOND_DESK, desk)
        bd.set_desk(desk, owner=self)

    def _bond_day(self) -> _dt.date:
        """The day the bonds are past their maturity against: the calculation's today (offline, the recorded file's)."""
        book = self.books.get("tto")
        return serial_to_date(book.engine.clock.today()) if book is not None else _dt.date.today()

    def _migrate_own_bonds(self) -> None:
        """The bonds typed into Tüm Kâğıtlar's old own rows (EK_EVREN!A6:A20): onto the desk's list, their kind to be
        asked of Bloomberg - once; the cells' values go (the rows are the list's now)."""
        if self.store.get("migrated.universe_own"):
            return
        sheet, first, last = self._OWN_ROWS
        stored = self.store.shared_inputs("tto")
        refs = [ref for ref in ("%s!A%d" % (sheet, r) for r in range(first, last + 1)) if ("tto", ref) in stored]
        desk = self._desk_now()
        shipped = {b["isin"] for b in bd.shipped()}
        for ref in refs:
            code = "".join(str(stored[("tto", ref)] or "").split()).upper()
            if bd.isin_valid(code) and code not in shipped and code not in desk["added"]:
                meta = self.store.shared_meta("tto", [ref]) or {}
                desk["added"][code] = dict(bd.waiting(code), by=meta.get("updated_by") or "", at=meta.get("updated_at") or now_iso())
        self.store.put(self.BOND_DESK, desk)
        self.store.clear_shared_inputs("tto", refs)
        self.store.put("migrated.universe_own", now_iso())

    @staticmethod
    def _universe_values(b: Dict[str, Any]) -> List[Any]:
        """What a bond's row of Tüm Kâğıtlar holds (``ex.UNI_WRITTEN``): ISIN, name, kind, coupon, maturity, kind code."""
        kind = b.get("kind") or ""
        cpn = b.get("coupon")
        if kind == "fixed" and isinstance(cpn, (int, float)):
            shown: Any = float(cpn) / 100.0
        elif kind == "cpi" and isinstance(cpn, (int, float)):
            shown = "reel %%%s" % ("%.2f" % cpn).replace(".", ",")
        else:
            shown = {"float": "TLREF", "frn": "FRN", "bill": "iskontolu", "zero": "iskontolu"}.get(kind, "")
        mat = date_to_serial(_dt.date.fromisoformat(b["maturity"])) if b.get("maturity") else None
        return [b["isin"], bd.short_label(b), bd.KINDS.get(kind) or "tür bekleniyor", shown, mat, kind]

    def _sync_universe(self) -> bool:
        """Tüm Kâğıtlar's rows, one a bond of the desk's list (on the calculation thread): a bond keeps its row, a new
        one takes the first free row (the kinds in their order, by maturity), a bond gone leaves its row empty.
        True when a cell changed."""
        book = self.books.get("tto")
        if book is None or ex.UNI_SHEET not in book.model.sheet_index:
            return False
        si = book.model.sheet_index[ex.UNI_SHEET]
        self._uni_day = self._bond_day()
        listed = bd.listed(self._uni_day)
        want = {b["isin"]: b for b in listed}
        rows = {isin: r for isin, r in self._uni_rows.items() if isin in want}
        taken = set(rows.values())
        free = [r for r in range(ex.UNI_FIRST, ex.UNI_LAST + 1) if r not in taken]
        order = {k: i for i, (k, _, _) in enumerate(ex.UNI_KINDS)}
        for b in sorted(listed, key=lambda x: (order.get(x.get("kind"), len(order)), x.get("maturity") or "9999", x["isin"])):
            if b["isin"] not in rows and free:
                rows[b["isin"]] = free.pop(0)
        filled = {r: want[isin] for isin, r in rows.items()}
        cells: Dict[Tuple[int, int], Any] = {}
        for r in range(ex.UNI_FIRST, ex.UNI_LAST + 1):
            values = self._universe_values(filled[r]) if r in filled else [None] * len(ex.UNI_WRITTEN)
            for col, v in zip(ex.UNI_WRITTEN, values):
                cells[(si, parse_a1("%s%d" % (col, r)))] = v
        if not self._uni_written:
            book.engine.declare_inputs(cells.keys(), group="tto-universe")     # one dependency for the whole list
        changed = {k: v for k, v in cells.items() if k not in self._uni_written or self._uni_written[k] != v
                   or type(self._uni_written[k]) is not type(v)}
        if changed:
            book.engine.set_inputs(changed)
            self._uni_written.update(changed)
        self._uni_rows = rows
        return bool(changed)

    def _bbg_security(self, isin: str) -> str:
        """How DİBS RV names a bond to Bloomberg: "TRT150328T24 ISIN" (its N2), or "/isin/TRT150328T24"."""
        how = "ISIN"
        book = self.books.get("tto")
        try:
            si, rc = book.cell("DİBS RV!N2")
            v = book.engine.input_value[si].get(rc)
            v = book.engine.base_value(si, rc) if v is None else v
            if isinstance(v, str) and v.strip():
                how = v.strip()
        except (AttributeError, KeyError, ValueError):
            pass
        return "/isin/" + isin if how.lower() == "/isin/" else "%s %s" % (isin, how)

    def _bond_facts(self, codes: List[str], wait: float = 0.0) -> Dict[str, Optional[Dict[str, Any]]]:
        """What Bloomberg says of each bond (``bd.FACTS``) - ``None`` for one it has not answered yet, asked again for
        up to ``wait`` seconds (a connected Bloomberg answers within a second or two)."""
        from .marketdata.base import REQUESTING, bdp_key
        end = time.time() + wait
        while True:
            out: Dict[str, Optional[Dict[str, Any]]] = {}
            for code in codes:
                sec = self._bbg_security(code)
                got = {f: self.provider.get_bdp(bdp_key(sec, f)) for f in bd.FACTS}
                out[code] = None if any(isinstance(v, str) and v == REQUESTING for v in got.values()) else got
            if all(v is not None for v in out.values()) or time.time() >= end or self._stop.is_set():
                return out
            time.sleep(0.2)

    def _classify_pending(self, wait: float = 0.0) -> bool:
        """The kind of the bonds added that Bloomberg has not told yet, asked again; a bond Bloomberg says is not a TL
        one, or does not know, leaves the list (its reason kept).  True when the list changed."""
        codes = bd.pending()
        if not codes:
            return False
        self._uni_tried = time.time()
        facts = self._bond_facts(codes, wait)
        changed = False
        with self._desk_lock:
            desk = self._desk_now()
            for code in codes:
                was = desk["added"].get(code)
                if facts.get(code) is None or was is None or was.get("kind"):
                    continue
                rec, why = bd.classify(code, facts[code])
                if rec is not None:
                    desk["added"][code] = dict(rec, by=was.get("by") or "", at=was.get("at") or now_iso())
                    changed = True
                elif why != "pending":
                    desk["added"].pop(code)
                    desk["refused"][code] = {"why": why, "by": was.get("by") or "", "at": now_iso()}
                    changed = True
            if changed:
                self._save_desk(desk)
        if changed:
            self.et.call(self._sync_universe)
            self.bump()
        return changed

    def bond_list_add(self, user: str, values: List[Any]) -> Dict[str, Any]:
        """Bonds onto the desk's list (Tüm Kâğıtlar), for everyone, each ISIN once: its kind, maturity, coupon and
        name from Bloomberg, and it goes into its kind's group.  A bond Bloomberg has not answered for yet joins the list
        and waits there for its kind; one Bloomberg says is not a TL bond, does not know, or is past its maturity is
        refused.  A bond taken off earlier comes back."""
        user = self.require_user(user)
        wanted = self._isins(values)
        day = self._bond_day()
        on = {b["isin"] for b in bd.listed(day)}
        skipped = [c for c in wanted if c in on]
        todo = [c for c in wanted if c not in on]
        known = {c: bd.by_isin(c) for c in todo}
        ask = [c for c in todo if not (known[c] or {}).get("kind")]
        facts = self._bond_facts(ask, self.BOND_WAIT) if ask else {}
        added: List[Dict[str, Any]] = []
        waiting: List[str] = []
        refused: List[Dict[str, Any]] = []
        shipped = {x["isin"] for x in bd.shipped()}
        with self._desk_lock:
            desk = self._desk_now()
            room = ex.UNI_ROWS - len(bd.listed(day))
            for code in todo:
                b = known.get(code)
                if not (b or {}).get("kind"):
                    b, why = bd.classify(code, facts[code]) if facts.get(code) is not None else (None, "pending")
                    if why not in ("", "pending"):
                        refused.append({"isin": code, "why": why, "text": self._refusal(why)})
                        continue
                    if b is None:
                        b = bd.waiting(code)
                if b.get("maturity") and b["maturity"] < day.isoformat():
                    refused.append({"isin": code, "why": "matured", "text": self._refusal("matured")})
                    continue
                if room <= 0:
                    refused.append({"isin": code, "why": "full", "text": self._refusal("full")})
                    continue
                room -= 1
                if code not in shipped and not (desk["added"].get(code) or {}).get("kind"):
                    desk["added"][code] = dict(b, by=user, at=now_iso())          # (one added before keeps its record)
                desk["removed"].pop(code, None)
                desk["refused"].pop(code, None)
                if not b.get("kind"):
                    waiting.append(code)
                added.append({"isin": code, "label": bd.short_label(b), "kind": b.get("kind"),
                              "kind_text": bd.KINDS.get(b.get("kind") or "", "")})
            if added:
                self._save_desk(desk)
        if added:
            self.et.call(self._sync_universe)
            self.bump()
        return {"added": added, "skipped": skipped, "waiting": waiting, "refused": refused,
                "free": ex.UNI_ROWS - len(bd.listed(day)), "gen": self.gen}

    def bond_list_remove(self, user: str, isin: str) -> Dict[str, Any]:
        """A bond off the desk's list (Tüm Kâğıtlar), for everyone - and off the trading list when it is on it.  The
        dashboard still knows it (a chat line about it, its card)."""
        user = self.require_user(user)
        code = "".join(str(isin or "").split()).upper()
        if not bd.isin_valid(code):
            raise ServiceError("ISIN değil ya da kontrol hanesi tutmuyor: %s" % (code or "(boş)"))
        if code not in {b["isin"] for b in bd.listed(self._bond_day())}:
            return {"isin": code, "removed": False, "trading": False, "gen": self.gen}
        trading = self.bond_flag(user, code, False)["removed"] > 0
        with self._desk_lock:
            desk = self._desk_now()
            desk["removed"][code] = {"by": user, "at": now_iso()}
            self._save_desk(desk)
        self.et.call(self._sync_universe)
        self.bump()
        return {"isin": code, "removed": True, "trading": trading, "gen": self.gen}

    def _universe_columns(self, book, user: Optional[str], data: Dict[str, Any], loc) -> None:
        """Tüm Kâğıtlar, completed: the bonds kind by kind (a caption row each, a bond whose kind Bloomberg has not told
        yet last), by maturity; ☆ / ★ (onto / off the trading list), today's Broker Chat board, ▸ (the card) and ✕ (off
        the list)."""
        rows, rnums, cols = data.get("rows") or [], data.get("r") or [], list(data.get("c") or [])
        if not rows or ex.UNI_SHEET not in book.model.sheet_index:
            return
        si = book.model.sheet_index[ex.UNI_SHEET]
        calc = self._calc(user, book)
        said = self._board_bonds(user)
        flag_at = cols.index("H") if "H" in cols else None
        kind_col, mat_col = parse_a1("%s1" % ex.UNI_KIND) % COLS, parse_a1("E1") % COLS
        desk = bd.desk()
        extra = len(self._BOARD_HEADS) + 2
        width = len(cols) + extra
        blank = [{"t": "", "k": ""} for _ in range(extra)]
        top: List[Tuple[List[Dict[str, Any]], int]] = []
        foot: List[Tuple[List[Dict[str, Any]], int]] = []
        groups: Dict[str, List[Tuple[Tuple[float, str], List[Dict[str, Any]], int]]] = {k: [] for k, _, _ in ex.UNI_KINDS}
        waiting: List[Tuple[Tuple[float, str], List[Dict[str, Any]], int]] = []
        for i, r in enumerate(rnums):
            row = rows[i]
            if r < ex.UNI_FIRST or r > ex.UNI_LAST:
                if r == 4:
                    row.extend([{"t": t, "k": "s", "b": 1, "f": "hd", "tip": tip} for t, tip in self._BOARD_HEADS]
                               + [{"t": "Kart", "k": "s", "b": 1, "f": "hd", "tip": "Kâğıdın bütün bilgisi tek pencerede"},
                                  {"t": "Çıkar", "k": "s", "b": 1, "f": "hd", "tip": "Kâğıdı Tüm Kâğıtlar listesinden çıkar (herkes için)"}])
                else:
                    row.extend(dict(c) for c in blank)
                (top if r < ex.UNI_FIRST else foot).append((row, r))
                continue
            v = calc.get(si, r, 1)
            code = "".join(str(v).split()).upper() if isinstance(v, str) else ""
            if not code:
                continue
            if flag_at is not None and flag_at < len(row):
                row[flag_at] = self._flag_cell(code, calc.get(si, r, 8) == "★")
            who = desk["added"].get(code)
            if who and who.get("by") and row:
                row[0] = dict(row[0], tip="Listeye ekleyen: %s · %s" % (who["by"], str(who.get("at") or "")[:16].replace("T", " ")))
            row.extend(self._bond_cells(said.get(code), loc)
                       + [{"t": "▸", "k": "s", "cls": "act cardlink", "tip": "Kâğıt kartı: " + code},
                          {"t": "✕", "k": "s", "cls": "act unlist", "tip": "Tüm Kâğıtlar listesinden çıkar: " + code}])
            mat = calc.get(si, r, mat_col)
            item = ((mat if type(mat) is float else 1e9, code), row, r)
            kind = calc.get(si, r, kind_col)
            (groups[kind] if kind in groups else waiting).append(item)

        def caption(text: str) -> List[Dict[str, Any]]:
            return [{"t": text, "k": "s", "b": 1, "cls": "grouphead", "cs": width}] + [{"t": "", "k": ""} for _ in range(width - 1)]

        out: List[Tuple[List[Dict[str, Any]], int]] = [x for x in top if x[1] != ex.UNI_FIRST - 1]
        for kind, cap, _ in ex.UNI_KINDS:
            if groups[kind]:
                out.append((caption("%s · %d kâğıt" % (cap, len(groups[kind]))), 0))
                out.extend((row, r) for _, row, r in sorted(groups[kind], key=lambda x: x[0]))
        if waiting:
            out.append((caption("Türü bekleniyor (Bloomberg) · %d kâğıt" % len(waiting)), 0))
            out.extend((row, r) for _, row, r in sorted(waiting, key=lambda x: x[0]))
        if not any(groups.values()) and not waiting:
            out.append((caption("Liste boş: + ISIN ekle ile kâğıt ekleyin"), 0))
        refused = [(isin, x) for isin, x in (self._desk_now()["refused"] or {}).items()
                   if str(x.get("at") or "") >= (_dt.date.today() - _dt.timedelta(days=7)).isoformat()]
        if refused:
            text = "Listeye alınmayan: " + " · ".join("%s (%s)" % (isin, self._refusal(x.get("why") or "")) for isin, x in refused)
            out.append(([{"t": text, "k": "s", "cls": "soft", "cs": width}] + [{"t": "", "k": ""} for _ in range(width - 1)], 0))
        out.extend(foot)
        data["rows"] = [row for row, _ in out]
        data["r"] = [r for _, r in out]
        self._universe_quote_marks(book, calc, si, data["rows"], data["r"], cols, loc)
        data["c"] = cols + [h for h, _ in self._BOARD_HEADS] + ["Kart", "Çıkar"]
        data["added"] = int(data.get("added") or 0) + extra

    def _universe_quote_marks(self, book, calc, si: int, rows, rnums, cols: List[str], loc) -> None:
        """Tüm Kâğıtlar: each bond's bid / ask ("–" where no order stands, the size of a live one in the tip) and,
        for a bond on the trading list whose price there is no live quote, DİBS RV's yield, ASW and signal soft."""
        rv = book.model.sheet_index.get("DİBS RV")
        soft = [index_to_col(ex._col("N") + k) for k, (col, _, _) in enumerate(ex.UNI_RV) if col != "AI"]     # not DV01
        sides = [(vis, size, raw, side) for vis, size, raw, side in (("I", ex.UNI_SIZE[0], "V", "bid"), ("J", ex.UNI_SIZE[1], "W", "ask"))
                 if vis in cols]
        for i, r in enumerate(rnums):
            def v(col: str) -> Any:
                return calc.get(si, r, parse_a1("%s1" % col) % COLS)
            if r < ex.UNI_FIRST or not v("U"):
                continue
            for vis, size, raw, side in sides:
                j = cols.index(vis)
                if j < len(rows[i]):
                    rows[i][j] = self._quote_cell(rows[i][j], v(size), v(raw), side, loc)
            at = v("T")                                       # the bond's place on the trading list
            q = self._rv_quote(calc, rv, ex.LIVE_FIRST - 1 + int(at)) if rv is not None and type(at) is float else None
            if q and q["stale"]:
                for col in soft:
                    if col in cols and cols.index(col) < len(rows[i]):
                        rows[i][cols.index(col)] = self._soft(rows[i][cols.index(col)], q["tip"])

    #: the order of the kinds in the trading summary: DİBS RV's types (B / S / T / F / E)
    @staticmethod
    def _repo_note(txt: Callable[[str], str], layout: Dict[str, Any], row: int) -> str:
        """Why the T0 → T1 repo is not given while both value dates have a price: the prices are not of the same
        day (the repo is worked out only from prices of one day: live quotes are today's, a last trade is of its
        day)."""
        w = ex.LIVE_REPO[0]
        if txt("%s%d" % (w, row)) or not all(txt("%s%d" % (layout["mid"][k], row)) for k in (0, 1)):
            return ""
        days = [txt("%s%d" % (layout["day"][k], row)) for k in (0, 1)]
        if days[0] and days[0] == days[1]:
            return ""

        def said(k: int) -> str:
            live = all(txt("%s%d" % (layout["size"][k][side], row)) not in ("", "0") for side in ("bid", "ask"))
            return "%s %s: %s" % (layout["groups"][k]["cap"], "canlı kota" if live else "son işlem", days[k] or "yok")
        return "T0 ve T1 fiyatları aynı güne ait değil (%s · %s): repo hesaplanmadı" % (said(0), said(1))

    def _repo_cell(self, cell: Callable[..., Dict[str, Any]], live: Optional[int], r: int) -> Dict[str, Any]:
        """The trading summary's T0 → T1 repo: the value, or a dash that says why there is none."""
        if live is None:
            return {"t": "", "k": ""}
        got = cell(ex.LIVE_REPO[0], r, live)
        if str(got.get("t") or "").strip():
            return got

        def txt(addr: str) -> str:
            m = re.match(r"([A-Z]+)(\d+)$", addr)
            return str(cell(m.group(1), int(m.group(2)), live).get("t") or "") if m else ""

        note = self._repo_note(txt, ex._live_cols(), r)
        return {"t": "–", "k": "s", "cls": "soft", "tip": note} if note else got

    _TYPE_GROUPS = (("B", "Bono · kuponsuz"), ("S", "Sabit kuponlu"), ("T", "TLREF'e endeksli"), ("F", "FRN"),
                    ("E", "TÜFE'ye endeksli"))

    #: the trading list's nominal for a round USD DV01: what the desk sizes a bond trade by
    USD_DV01 = 1000.0
    USD_DV01_STEP = 5e6
    USD_DV01_HEAD = "1.000$ DV01 nominal"

    @staticmethod
    def _usdtry_mid(book: Book, calc) -> Optional[float]:
        """USDTRY as the desk's sheets use it (VİOP!L99 / L100: the manual spot, else Bloomberg's bid / ask), mid."""
        vi = book.model.sheet_index.get("VIOP")
        if vi is None:
            return None
        sides = [x for x in (calc.get(vi, 99, 12), calc.get(vi, 100, 12)) if type(x) is float and x > 0]
        return sum(sides) / len(sides) if sides else None

    def _usd_dv01_cell(self, dv01: Any, spot: Optional[float], kind: Any, loc) -> Dict[str, Any]:
        """The TL nominal whose DV01 is USD 1,000: 1,000 × USDTRY ÷ (DV01 per 1 mn), to the nearest 5 mn."""
        if type(dv01) is not float or dv01 <= 0 or not spot:
            return {"t": "", "k": ""}
        exact = self.USD_DV01 * spot / dv01 * 1e6
        nominal = max(1, round(exact / self.USD_DV01_STEP)) * self.USD_DV01_STEP
        what = "spread DV01'i (TLREF)" if kind == "T" else "DV01"
        tip = ("%s USD %s için nominal: %s × USDTRY %s ÷ %s TL (1 mn başına) = %s, 5 mn'a yuvarlı"
               % (numfmt.format_value(self.USD_DV01, "#,##0", loc), what, numfmt.format_value(self.USD_DV01, "#,##0", loc),
                  numfmt.format_value(spot, "0.0000", loc), numfmt.format_value(dv01, "0.0", loc),
                  numfmt.format_value(exact, "#,##0", loc)))
        return {"t": numfmt.format_value(nominal / 1e6, "#,##0", loc) + "m", "v": nominal, "k": "n", "tip": tip}

    def _trading_table(self, user: Optional[str], loc) -> Dict[str, Any]:
        """The trading list at a glance (generated): the bonds of DİBS RV kind by kind, by maturity - the price on
        the value date the bond is priced on (bid, ask, the last trade and when), what DİBS RV makes of it (yield,
        ASW, cheap / rich, signal, duration, DV01, carry), the repo T0 -> T1 implies and today's chat board."""
        book = self.books.get("tto")
        heads = ["★", "Kâğıt", "ISIN", "Vade", "Kalan yıl", "Valör", "Bid", "Ask", "Son işlem", "Ne zaman", "Getiri %",
                 "ASW / DM", "Pahalı / ucuz", "Sinyal", "Mod. süre", "DV01 / 1mn", self.USD_DV01_HEAD, "C+R (bp)",
                 "T0→T1 repo %"] + [h for h, _ in self._BOARD_HEADS] + ["Kart"]
        rows: List[List[Dict[str, Any]]] = [[{"t": x, "k": "s", "b": 1, "f": "hd"} for x in heads]]
        out = {"rows": rows, "r": [], "c": [index_to_col(k + 1) for k in range(len(heads))], "added": len(heads)}
        if book is None or "DİBS RV" not in book.model.sheet_index:
            return out
        si = book.model.sheet_index["DİBS RV"]
        calc = self._calc(user, book)
        R = self.renderers[book.id]
        live = book.model.sheet_index.get(ex.LIVE_SHEET)
        said = self._board_bonds(user)
        today = _dt.date.fromisoformat(self.today_iso())
        spot = self._usdtry_mid(book, calc)

        def cell(c: str, r: int, s: int = si) -> Dict[str, Any]:
            got = R.cell(calc, s, r, parse_a1("%s1" % c) % COLS, loc)
            keep = {k: got[k] for k in ("t", "v", "k", "c", "b") if k in got}
            keep.setdefault("t", "")
            keep.setdefault("k", "")
            return keep

        from . import bonds as bd
        bonds: Dict[str, List[Tuple[Any, List[Dict[str, Any]]]]] = {g: [] for g, _ in self._TYPE_GROUPS}
        for r in range(5, 55):
            isin = calc.get(si, r, 1)
            if not isinstance(isin, str) or not isin.strip():
                continue
            code = "".join(isin.split()).upper()
            known = bd.by_isin(code)
            # the kind and the maturity: the desk's list knows them; DİBS RV knows them from Bloomberg (a bond the
            # list does not have, or one just added while the recorded file is shown, has only what Bloomberg says)
            kind = {"bill": "B", "zero": "B", "fixed": "S", "float": "T", "frn": "F", "cpi": "E"}.get((known or {}).get("kind")) \
                or calc.get(si, r, 4)
            mat = calc.get(si, r, 5)
            if type(mat) is not float and known:
                mat = date_to_serial(_dt.date.fromisoformat(known["maturity"]))
            src = calc.get(si, r, parse_a1("BS1") % COLS)
            sec = calc.get(si, r, parse_a1("BT1") % COLS)
            seen = self.trades_seen(sec) if isinstance(sec, str) else None
            when = cell("I", r)
            if seen:
                when = {"t": "bugün " + seen["time"], "k": "s", "cls": "fresh",
                        "tip": "Dashboard'un bu kâğıtta işlem gördüğü an · Bloomberg son işlem günü: " + (when.get("t") or "")}
            years = (serial_to_date(mat) - today).days / 365.25 if type(mat) is float else None
            label = cell("B", r, live) if live is not None else {"t": code, "k": "s"}
            if known and label.get("t") in ("", code):
                label = {"t": bd.short_label(known), "k": "s", "b": 1}
            due = cell("E", r)
            if not str(due.get("t") or "").strip() and type(mat) is float:
                due = {"t": numfmt.format_value(mat, "dd.mm.yyyy", loc), "v": mat, "k": "n"}
            q = self._rv_quote(calc, si, r)
            priced = [cell("T", r), cell("Z", r), cell("AB", r), dict(cell("AC", r), b=1)]
            if q["stale"]:
                priced = [self._soft(c, q["tip"]) for c in priced]
            line = [self._flag_cell(code, True), label, {"t": code, "k": "s", "cls": "soft"}, due,
                    {"t": numfmt.format_value(years, "0.00", loc), "v": years, "k": "n"} if years is not None else {"t": "", "k": ""},
                    {"t": str(src or ""), "k": "s", "cls": "soft"},
                    self._quote_cell(cell("K", r), q["bid"], q["raw_bid"], "bid", loc),
                    self._quote_cell(cell("L", r), q["ask"], q["raw_ask"], "ask", loc), dict(cell("AS", r), b=1), when] + priced + \
                [cell("AG", r), cell("AI", r), self._usd_dv01_cell(calc.get(si, r, parse_a1("AI1") % COLS), spot, kind, loc),
                 cell("AO", r), self._repo_cell(cell, live, r)]
            line += self._bond_cells(said.get(code), loc) + [{"t": "▸", "k": "s", "cls": "act cardlink", "tip": "Kâğıt kartı: " + code}]
            group = kind if kind in bonds else "S"
            bonds[group].append((mat if type(mat) is float else 1e9, line))
        for g, caption in self._TYPE_GROUPS:
            if not bonds[g]:
                continue
            rows.append([{"t": "%s · %d" % (caption, len(bonds[g])), "k": "s", "b": 1, "cls": "grouphead", "cs": len(heads)}]
                        + [{"t": "", "k": ""} for _ in heads[1:]])
            rows.extend(line for _, line in sorted(bonds[g], key=lambda x: x[0]))
        if len(rows) == 1:
            rows.append([{"t": "Trading listesi boş: Tüm Kâğıtlar sayfasında ☆ ile ekleyin", "k": "s", "cls": "soft", "cs": len(heads)}]
                        + [{"t": "", "k": ""} for _ in heads[1:]])
        out["r"] = list(range(1, len(rows) + 1))
        return out

    # ================================================================== watching the market
    def _watch_call(self, fn, *args):
        try:
            return self.et.call(fn, *args)
        except (KeyError, ValueError) as exc:
            raise ServiceError(str(exc.args[0]) if exc.args else "hücre bulunamadı")

    #: one list of the watch page, alone (a box of it): the watch list, the alarms, what fired today
    WATCH_PARTS = ("items", "alarms", "fired")

    def watch_view(self, user: str, locale: Optional[str] = None, days: Any = 60, part: Optional[str] = None) -> Dict[str, Any]:
        """The user's watch list (with each item's z-score over ``days`` closes) and alarms, what fired today,
        the desk's notes.  ``part``: one of ``WATCH_PARTS`` alone - a box of it on a launchpad, in the side drawer,
        in a window of its own (the other lists and the desk's alarms are not read)."""
        user = self.require_user(user)
        if part not in (None, "") and part not in self.WATCH_PARTS:
            raise ServiceError("bilinmeyen liste: %s" % str(part)[:40])
        loc = numfmt.get_locale(locale or self.settings.locale)
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 60

        def run() -> Dict[str, Any]:
            if part:
                return self.watch.snapshot(user, loc, days, part)
            out = self.watch.snapshot(user, loc, days)
            out["desk"] = self._desk_view(user, self.watch.desk_rows(loc))
            return out

        out = self.et.call(run)
        out["gen"] = self.gen
        return out

    @staticmethod
    def _subject(subject: Any = None, book_id: str = "tto", ref: str = "") -> Dict[str, Any]:
        """What is watched: a subject as the page sends it, or (as before) a cell of a book."""
        if isinstance(subject, dict) and subject.get("kind"):
            return subject
        if not ref:
            raise ServiceError("izlenecek şey belli değil")
        return {"kind": "cell", "book": book_id or "tto", "ref": ref}

    def watch_catalog(self, user: str) -> Dict[str, Any]:
        """What can be watched: OIS tenors, offshore tenors, the desk strip, VİOP contracts, bonds - and their measures."""
        self.require_user(user)
        return self.et.call(self.watch.catalog)

    def watch_preview(self, user: str, subject: Any = None, book_id: str = "tto", ref: str = "") -> Dict[str, Any]:
        """A subject's name and value now (before it is added; an expression is checked)."""
        user = self.require_user(user)
        return self._watch_call(self.watch.preview, user, self._subject(subject, book_id, ref))

    def watch_add(self, user: str, book_id: str = "tto", ref: str = "", label: str = "", unit: str = "",
                  subject: Any = None, hint: str = "") -> Dict[str, Any]:
        """Watch something (a subject, or a cell - one that shows a bond, a VİOP contract, an OIS or offshore tenor
        is watched as that).  ``label``: the user's name for it; ``hint``: a cell's name from its table."""
        user = self.require_user(user)
        s = self._subject(subject, book_id, ref)
        if s["kind"] == "cell":
            self._book(s.get("book") or "tto")
            if unit:
                s = dict(s, show=unit)
        res = self._watch_call(self.watch.add, user, s, str(label or ""), str(hint or ""))
        self.bump()
        out = {"added": res["added"], "count": len(res["items"])}
        if res.get("item"):
            out["item"] = res["item"]
        return out

    def watch_preset(self, user: str, group: str) -> Dict[str, Any]:
        user = self.require_user(user)
        res = self._watch_call(self.watch.add_preset, user, str(group or ""))
        self.bump()
        return res

    def watch_remove(self, user: str, item_id: str) -> Dict[str, Any]:
        user = self.require_user(user)
        n = self.watch.remove(user, str(item_id or ""))
        self.bump()
        return {"removed": n}

    def watch_update(self, user: str, item_id: str, label: Optional[str] = None, unit: Optional[str] = None,
                     move: Optional[int] = None) -> Dict[str, Any]:
        user = self.require_user(user)
        self._watch_call(self.watch.update, user, str(item_id or ""), label, unit, move)
        self.bump()
        return {"ok": True}

    def watch_base(self, user: str, item_id: Optional[str] = None) -> Dict[str, Any]:
        """Take the level now as the reference of one item (or of all): the change is told since then as well."""
        user = self.require_user(user)
        n = self.et.call(self.watch.set_base, user, item_id or None)
        self.bump()
        return {"taken": n}

    @staticmethod
    def _alarm_level(level: Any) -> float:
        """An alarm's level as typed (35,80 · -12,5 · 250)."""
        try:
            return float(str(level).strip().replace(" ", "").replace("−", "-").replace(",", ".")) if not isinstance(level, (int, float)) else float(level)
        except (TypeError, ValueError):
            raise ServiceError("seviye bir sayı olmalı")

    def alarm_add(self, user: str, book_id: str = "tto", ref: str = "", op: str = "", level: Any = None, label: str = "",
                  note: str = "", subject: Any = None, mode: str = "level", minutes: Any = None, days: Any = None) -> Dict[str, Any]:
        """An alarm on anything that can be watched: on its level (typed as the subject is shown: 35,80 on a rate
        in per cent, 250 on a spread in bp), on a move (from the day's open, from now, from the watch list's
        reference, within the last minutes; bp for rates and spreads) or on its z-score."""
        user = self.require_user(user)
        s = self._subject(subject, book_id, ref)
        if s["kind"] == "cell":
            self._book(s.get("book") or "tto")
        lvl = self._alarm_level(level)
        res = self._watch_call(self.watch.add_alarm, user, s, str(op or ""), lvl, str(label or ""), str(note or ""),
                               str(mode or "level"), minutes, days)
        self.bump()
        return res

    def alarm_remove(self, user: str, alarm_id: str) -> Dict[str, Any]:
        user = self.require_user(user)
        n = self.watch.remove_alarm(user, str(alarm_id or ""))
        self.bump()
        return {"removed": n}

    def alarm_rearm(self, user: str, alarm_id: str, level: Any = None) -> Dict[str, Any]:
        user = self.require_user(user)
        lvl = None
        if level not in (None, ""):
            try:
                lvl = float(str(level).replace(",", "."))
            except (TypeError, ValueError):
                raise ServiceError("seviye bir sayı olmalı")
        res = self._watch_call(self.watch.rearm, user, str(alarm_id or ""), lvl)
        self.bump()
        return {"alarm": res}

    def alarms_fired(self, user: str, since: int = 0, desk: Any = None) -> Dict[str, Any]:
        """The user's alarms that fired today after ``since`` (the last one the page has shown) - and the desk's:
        the lines of its day's log after ``desk`` and the firings nobody has answered (the top bar's count)."""
        user = self.require_user(user)
        mine = [e for e in self.watch.fired() if e.get("user") == user]
        last = max([int(e.get("seq") or 0) for e in self.watch.fired()] or [0])
        return {"fired": [e for e in mine if int(e.get("seq") or 0) > int(since or 0)], "last": last,
                "desk": self.desk_alarms.since(desk, user)}

    # ================================================================== the desk's alarms (deskalarms.py)
    def _desk_view(self, user: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """The desk's alarms as the alarms page shows them: the alarms an administrator set (with their last firing
        of the day and this user's own mute of them), the system's, the day's log, what nobody answered, the settings."""
        from .deskalarms import ACTIONS
        desk = self.desk_alarms
        entries = desk.log()

        def last_fired(alarm: str) -> Optional[Dict[str, Any]]:
            return next((e for e in reversed(entries) if e.get("alarm") == alarm and e.get("kind") == "fired"), None)

        def mine(alarm: str) -> Optional[Dict[str, Any]]:
            until = desk.muted(alarm, user)                # muting is personal: only this user's own mute
            return {"until": until} if until else None

        for r in rows:
            e = last_fired(r["id"])
            r["entry"] = e if e is not None and (not r.get("active") or not e.get("closed_at")) else None
            r["mute"] = mine(r["id"])
            r["by_name"] = desk.name(r.get("by"))
        system = self.ops.system_rows()
        for s in system:
            s["entry"] = last_fired("sys:" + s["kind"])
            s["mute"] = mine("sys:" + s["kind"])
        return {"alarms": rows, "system": system, "log": entries, "open": desk.for_user(desk.opened(entries), user),
                "settings": self.ops.settings(), "admin": (self.store.account(user) or {}).get("role") == "admin",
                "live": self.mode == "live", "actions": ACTIONS}

    def _desk_alarm(self, alarm_id: str) -> Dict[str, Any]:
        a = next((x for x in self.watch.desk_list() if x["id"] == alarm_id), None)
        if a is None:
            raise ServiceError("masa alarmı bulunamadı", 404)
        return a

    def desk_alarm_add(self, user: str, book_id: str = "tto", ref: str = "", op: str = "", level: Any = None, label: str = "",
                       note: str = "", subject: Any = None, mode: str = "level", minutes: Any = None, days: Any = None) -> Dict[str, Any]:
        """An alarm for the whole desk (administrators only): as a personal one, but read on the market's values and
        told on everyone's screen."""
        me = self.require_admin(user)
        if mode == "ref":                                  # a reference is one user's (their watch list's ⟲)
            raise ServiceError("masa alarmında izleme referansı yok: açılıştan, şimdiki seviyeden ya da son dakikalarda seçin")
        s = self._subject(subject, book_id, ref)
        if s["kind"] == "cell":
            self._book(s.get("book") or "tto")
        lvl = self._alarm_level(level)

        def run() -> Dict[str, Any]:       # on the calculation thread, as the watch's rounds: "set" is logged before a firing
            res = self.watch.add_alarm("", s, str(op or ""), lvl, str(label or ""), str(note or ""), str(mode or "level"),
                                       minutes, days, me)
            self.desk_alarms.note("set", res["alarm"]["id"], res["alarm"]["label"], res["condition"], by=me)
            return res

        res = self._watch_call(run)
        self.bump()
        return res

    def desk_alarm_remove(self, user: str, alarm_id: str) -> Dict[str, Any]:
        me = self.require_admin(user)
        a = self._desk_alarm(str(alarm_id or ""))

        def run() -> int:
            n = self.watch.remove_alarm("", a["id"])
            self.desk_alarms.close(a["id"], "silindi")
            self.desk_alarms.note("removed", a["id"], a["label"], self.watch.cond_text(a), by=me)
            return n

        n = self._watch_call(run)
        self.bump()
        return {"removed": n}

    def desk_alarm_rearm(self, user: str, alarm_id: str, level: Any = None) -> Dict[str, Any]:
        me = self.require_admin(user)
        a = self._desk_alarm(str(alarm_id or ""))
        lvl = None if level in (None, "") else self._alarm_level(level)

        def run() -> Dict[str, Any]:       # the earlier firing closed before a round of the watch can fire it again
            res = self.watch.rearm("", a["id"], lvl)
            self.desk_alarms.close(a["id"], "yeniden kuruldu")
            self.desk_alarms.note("rearmed", a["id"], res["label"], self.watch.cond_text(res), by=me)
            return res

        res = self._watch_call(run)
        self.bump()
        return {"alarm": res}

    def desk_alarm_ack(self, user: str, seq: Any) -> Dict[str, Any]:
        """"Gördüm, ben bakıyorum": a firing of the desk's alarms answered for everyone (by anyone signed in)."""
        from .deskalarms import DeskAlarmError
        me = self.require_user(user)
        try:
            entry = self.desk_alarms.ack(me, seq)
        except DeskAlarmError as exc:
            raise ServiceError(str(exc), 404)
        self.bump()
        return {"entry": entry}

    def desk_alarm_mute(self, user: str, alarm: Any, minutes: Any) -> Dict[str, Any]:
        """Mute one of the desk's alarms (an id, or "sys:feed" …) for oneself for a while: it still fires and everyone
        else is told of it; the one who muted it is not."""
        from .deskalarms import SYSTEM, DeskAlarmError
        me = self.require_user(user)
        alarm = str(alarm or "")
        label = SYSTEM[alarm[4:]] if alarm.startswith("sys:") and alarm[4:] in SYSTEM else self._desk_alarm(alarm)["label"]
        try:
            out = self.desk_alarms.mute(me, alarm, minutes, label)
        except DeskAlarmError as exc:
            raise ServiceError(str(exc))
        self.bump()
        return out

    def desk_alarm_settings(self, user: str, values: Any) -> Dict[str, Any]:
        """The desk's settings (administrators): market hours, when the data is stale, the system alarms."""
        from .ops import changes
        me = self.require_admin(user)
        before = self.ops.settings()
        try:
            cur = self.ops.set_settings(values if isinstance(values, dict) else {})
        except ValueError as exc:
            raise ServiceError(str(exc))
        said = changes(before, cur)
        if said:
            self.desk_alarms.note("settings", "ayarlar", "Ayarlar", said, by=me)
        self.bump()
        return cur

    def heat_view(self, user: str, basis: str = "close", locale: Optional[str] = None) -> Dict[str, Any]:
        """The heat map of the curves: every point's change since the previous close, the day's open or the
        user's reference."""
        user = self.require_user(user)
        loc = numfmt.get_locale(locale or self.settings.locale)
        out = self.et.call(self.watch.heat, user, str(basis or "close"), loc)
        out["gen"] = self.gen
        return out

    def watch_history(self, user: str, subject: Any = None) -> Dict[str, Any]:
        """A watched subject's daily closes (the market history's, its parts', or the dashboard's own record) and its
        value now - what a click on a watch item or a point of the heat map draws."""
        user = self.require_user(user)
        if not isinstance(subject, dict) or not subject.get("kind"):
            raise ServiceError("izlenecek şey belli değil")

        def run() -> Dict[str, Any]:
            s = self.watch.check(subject)                  # what is not there to watch has no past either
            rd = self.watch._Reader(self.watch, user)
            value, show, _ = self.watch.resolve(s, rd)
            closes, source = self.watch.history(s, rd)
            return {"label": self.watch.label(s), "show": show, "value": value, "points": sorted(closes.items()),
                    "source": source, "today": self.today_iso()}

        return self._watch_call(run)

    def history_closes(self, user: Optional[str], sid: Any) -> Dict[str, Any]:
        """The daily closes of one series of the end-of-day matrix (a row clicked)."""
        self.require_user(user)
        try:
            return self.history.closes(str(sid or ""))
        except ValueError as exc:
            raise ServiceError(str(exc))

    def heat_ref(self, user: str) -> Dict[str, Any]:
        """Take the levels now as this user's reference of the heat map (the morning meeting)."""
        user = self.require_user(user)
        res = self.et.call(self.watch.heat_ref, user)
        self.bump()
        return res

    def notes_set(self, user: str, text: str) -> Dict[str, Any]:
        """The desk's notes of the day (shared): levels to watch, what was said at the morning meeting."""
        user = self.require_user(user)
        note = {"text": str(text or "")[:20000], "by": user, "at": _dt.datetime.now().strftime("%H:%M:%S")}
        self.store.put("desk.notes:%s" % self.today_iso(), note)
        self.bump()
        return note

    # ================================================================== ASW against FX swaps
    def _asw_fx_columns(self, book, user: Optional[str], data: Dict[str, Any], loc) -> None:
        """ASW against the FX swap curve next to ASW against OIS: the sheet's own calculation with the OIS quotes
        it builds its curve from (ASW!C65:R65) swapped for the FX swap implied rates of EK_FX - a tenor without
        one keeps its OIS quote.  Two columns on the right of the table: ASW FX and FX − OIS, in bp."""
        if ex.FXC_SHEET not in book.model.sheet_index or "ASW" not in book.model.sheet_index:
            return
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows:
            return
        si, fi = book.model.sheet_index["ASW"], book.model.sheet_index[ex.FXC_SHEET]
        base = self._calc(user, book)
        ov = dict(self._overlay(user, book)) if user else {}
        swapped = 0
        for k in range(len(ex.FXC_ROOTS)):
            v = base.get(fi, ex.FXC_FIRST + k, parse_a1("D1") % COLS)
            if type(v) is float:
                ov[(si, parse_a1("%s65" % index_to_col(3 + k)))] = v
                swapped += 1
        calc = Calc(book.engine, book.engine.shared, ov) if swapped else None
        r_col = parse_a1("R1") % COLS

        def bp(v: Any, signed: bool = False) -> Dict[str, Any]:
            if type(v) is not float:
                return {"t": "", "k": ""}
            cell = {"t": (("+" if signed and v > 0 else "") + numfmt.format_value(v, "0.0", loc)), "v": v, "k": "n"}
            if signed:
                cell["c"] = "pos" if v > 0 else ("neg" if v < 0 else None)
                if cell["c"] is None:
                    cell.pop("c")
            return cell

        for i, r in enumerate(rnums):
            if r == 6:
                rows[i].extend([{"t": "ASW FX (bp)", "k": "s", "b": 1, "f": "hd",
                                 "tip": "FX swap ima TRY eğrisine göre ASW (EK_FX: %d / %d vade fiyatlı)" % (swapped, len(ex.FXC_ROOTS))},
                                {"t": "FX − OIS (bp)", "k": "s", "b": 1, "f": "hd", "tip": "ASW FX − ASW OIS"}])
            elif 7 <= r <= 56 and calc is not None:
                ois, fx = base.get(si, r, r_col), calc.get(si, r, r_col)
                rows[i].extend([bp(fx), bp(fx - ois if type(fx) is float and type(ois) is float else None, True)])
            else:
                rows[i].extend([{"t": "", "k": ""}, {"t": "", "k": ""}])
        data["c"] = list(data.get("c") or []) + ["ASW FX", "FX−OIS"]
        data["added"] = int(data.get("added") or 0) + 2

    # ================================================================== BIST swaps against the TRY workbook's curves
    def _borsa_spread_columns(self, book, calc, user: Optional[str], data: Dict[str, Any], loc, rng: str) -> None:
        """The Borsa Swap tables' spreads to the OIS and the offshore mid curve (``tto.borsaspread``): the curves are
        the TRY workbook's, as the same user's calculation of it has them - their own inputs there apply, as on its
        pages."""
        tto = self.books.get("tto")
        if tto is not None:
            bsp.columns(book, calc, rng, data, loc, bsp.read_curves(tto, self._calc(user, tto)))

    def _board_bonds(self, user: Optional[str]) -> Dict[str, Dict[str, Any]]:
        """Today's Broker Chat board bond by bond: ISIN -> its row (resets applied), with the yields its prices
        imply on the DİBS RV screen."""
        today = self.today_iso()
        _, table, _ = self._broker_board(user, today, today)
        said = {r["isin"]: r for r in table if r.get("product") == "DIBS" and r.get("isin")}
        if said:
            self._bond_implied(user, [], list(said.values()))
        return said

    @staticmethod
    def _age_text(s: Any) -> str:
        """How old a quote is, as the Broker Chat board says it: "şimdi", "7 dk", "1 sa 5 dk"."""
        if type(s) is not float:
            return ""
        if s < 60:
            return "şimdi"
        m = int(s // 60)
        return "%d dk" % m if m < 60 else "%d sa %d dk" % (m // 60, m % 60)

    @staticmethod
    def _bond_cells(q: Optional[Dict[str, Any]], loc) -> List[Dict[str, Any]]:
        """A bond of today's Broker Chat board in four cells - empty for a bond nobody spoke of - by the board's rules:
        the brokers' best fresh bid and ask (a quote withdrawn, traded away or said before a reset is gone), the last
        trade (or a level said without a side, soft) and whose the bid and ask are and how old (``Kimde · yaş``).  A
        stale quote is never shown as current: a side with stale quotes only shows the freshest of them greyed, "bayat"
        with its broker and age beside it.  A bond with no quote standing has the time of its last word there; a board
        of a day gone by (no clock) the times instead of the ages."""
        if q is None:
            return [{"t": "", "k": ""} for _ in range(4)]
        unit = q.get("unit") or "px"
        age_text = Service._age_text

        def lvl(v: Any, extra: str = "", cls: str = "") -> Dict[str, Any]:
            if type(v) is not float:
                return {"t": "", "k": ""}
            cell = {"t": numfmt.format_value(v, "0.000" if unit == "px" else "0.00", loc) + extra, "v": v, "k": "n"}
            if cls:
                cell["cls"] = cls
            return cell

        def ago(stamp: Any, age: Any) -> str:
            return age_text(age) if type(age) is float else str(stamp or "")[11:16]

        cells: List[Dict[str, Any]] = []
        shown: Dict[str, Tuple[str, str, bool, Any]] = {}                       # side -> (house, age, stale, when)
        for side, name in (("bid", "bid"), ("ask", "offer")):
            v = q.get("best_" + side)
            if type(v) is float:
                by, when, age = q.get("best_" + side + "_by") or "kaynaksız", q.get("best_" + side + "_time"), q.get("best_" + side + "_age")
                shown[side] = (by, ago(when, age), False, age)
                cells.append(dict(lvl(v), tip="En iyi %s: %s · %s%s" % (name, by, str(when or "")[11:19],
                                                                       " (%s önce)" % age_text(age) if type(age) is float else "")))
                continue
            stale = [b for b in q.get("brokers") or [] if type(b.get(side)) is float and b.get(side + "_stale")]
            if not stale:
                cells.append({"t": "", "k": ""})
                continue
            b = max(stale, key=lambda x: x.get(side + "_time") or "")             # the freshest of the stale ones
            shown[side] = (b["by"] or "kaynaksız", ago(b.get(side + "_time"), b.get(side + "_age")), True, b.get(side + "_age"))
            cells.append(dict(lvl(b[side], "", "stale soft"), tip="Bayat, en iyi sayılmaz: %s %s · %s önce – taze %s yok"
                              % (b["by"] or "kaynaksız", lvl(b[side])["t"], age_text(b.get(side + "_age")), name)))
        last = lvl(q.get("last"), " · biz" if q.get("last_by") == "biz" else "",
                   "buy" if q.get("last_side") == "ask" else ("sell" if q.get("last_side") == "bid" else ""))
        if type(q.get("last")) is float:
            last["tip"] = "Son işlem: %s%s" % (str(q.get("last_time") or "")[11:19],
                                                " · " + q["last_src"] if q.get("last_src") and q.get("last_by") != "biz" else "")
        elif type(q.get("level")) is float:
            last = dict(lvl(q["level"], "", "soft"), tip="Seviye (işlem değil): " + (q.get("said") or ""))
        times = [x for x in (q.get("bid_time"), q.get("ask_time"), q.get("last_time"), q.get("level_time")) if x]
        if not shown:
            who = {"t": max(times)[-8:-3] if times else "", "k": "s", "al": "c",
                   "tip": "Duran kota yok · chat'te son söz: " + max(times) if times else ""}
        else:
            (b1, a1, s1, g1), (b2, a2, s2, g2) = shown.get("bid", shown.get("ask")), shown.get("ask", shown.get("bid"))
            if (b1, s1) == (b2, s2):
                older = max((g for g in (g1, g2) if type(g) is float), default=None)
                text = ("bayat · " if s1 else "") + b1 + " · " + (age_text(older) if older is not None else a1)
            else:
                text = " / ".join(("bayat " if st else "") + by + " " + ag for by, ag, st, _ in (shown[x] for x in ("bid", "ask") if x in shown))
            who = {"t": text, "k": "s", "al": "c", "cls": "who" + (" stale soft" if all(x[2] for x in shown.values()) else ""),
                   "tip": "\n".join("%s: %s · %s%s" % ("Bid" if x == "bid" else "Offer", shown[x][0], shown[x][1], " (bayat, en iyi sayılmaz)" if shown[x][2] else "")
                                    for x in ("bid", "ask") if x in shown)}
        return cells + [last, who]

    _BOARD_HEADS = [("Broker bid", "Broker Chat tahtasındaki en iyi taze bid (bono / kuponsuzda getiri); taze bid yoksa en yeni bayat "
                                   "bid soluk – en iyi sayılmaz. Geri çekilen, işlemle verilen ve tahta sıfırlanınca kalkan kota yok"),
                    ("Broker ask", "Broker Chat tahtasındaki en iyi taze offer; taze offer yoksa en yeni bayat offer soluk"),
                    ("Son işlem", "Bugün chat'te geçen son işlem (biz: bizim masanın); işlem yoksa tarafı söylenmemiş son seviye "
                                  "(ihale fiyatı gibi), soluk"),
                    ("Kimde · yaş", "Bid ve offer'ın hangi broker'da olduğu ve kaç dakika önce söylendiği (bayat sınırı masanın, Broker "
                                    "Chat tahtasında); bayatsa soluk. Duran kota yoksa kâğıt için chat'te söylenen son şeyin saati")]

    def _dibs_broker_columns(self, book, user: Optional[str], data: Dict[str, Any], loc) -> None:
        """The day's broker chat next to the DİBS RV table, by the Broker Chat board's rules (:meth:`_bond_cells`):
        per bond the brokers' best fresh bid and ask, the last trade, whose the quotes are and how old, the yield
        the mid of the fresh quotes stands for and how far it is from the screen's yield (bp; + : the brokers see it
        cheaper than the screen).  Of stale quotes only there is no yield and no distance - "bayat" says so."""
        sheet = "DİBS RV"
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows or sheet not in book.model.sheet_index:
            return
        si = book.model.sheet_index[sheet]
        calc = self._calc(user, book)
        self._rv_quote_marks(book, calc, si, data, loc)
        said = self._board_bonds(user)
        mkt = self._broker_market(user) if said else None
        stale_min = self._broker_stale_minutes()
        heads = self._BOARD_HEADS + [
            ("Broker getiri %", "Brokerların en iyi taze bid / offer ortasının ima ettiği getiri: ekran getirisi − (fiyat − ekran fiyatı) / "
                                "(ekran fiyatı · mod. süre); bonoda kotanın kendisi. Yalnız taze kotadan (taze kota yoksa taze son işlemden)"),
            ("Broker − ekran (bp)", "Broker orta getirisi − ekran getirisi (DİBS RV): + ise brokerlar kâğıdı ekrandan ucuz görüyor. "
                                    "Yalnız taze kotadan")]
        for i, r in enumerate(rnums):
            if r == 4:
                rows[i].extend([{"t": t, "k": "s", "b": 1, "f": "hd", "tip": tip} for t, tip in heads])
                continue
            q = None
            if 5 <= r <= 54:
                v = calc.get(si, r, 1)
                q = said.get("".join(str(v).split()).upper()) if isinstance(v, str) and v.strip() else None
            if q is None:
                rows[i].extend([{"t": "", "k": ""} for _ in heads])
                continue
            unit = q.get("unit") or "px"
            # the yield of the mid of the brokers' best fresh bid and offer (of one side when only one stands; of the
            # last trade - or level - when no side stands, and it is fresh itself): nothing stale goes into it
            imp = q.get("implied") or {}
            fresh = [k for k in ("last", "level") if type(q.get(k)) is float and not q.get(k + "_stale")]
            if unit == "yld":
                sides = [q[k] for k in ("best_bid", "best_ask") if type(q.get(k)) is float] or [q[k] for k in fresh][:1]
                screen = (self._bond_screen(mkt, q["isin"]) or {}).get("yield")
            else:
                sides = [imp[k] for k in ("best_bid", "best_ask") if type(imp.get(k)) is float] or \
                    [imp[k] for k in fresh if type(imp.get(k)) is float][:1]
                screen = imp.get("screen_yield")
            mid = sum(sides) / len(sides) if sides else None
            gap = (mid - screen) * 100.0 if mid is not None and type(screen) is float else None
            gap_cell: Dict[str, Any] = {"t": "", "k": ""}
            if gap is not None:
                gap_cell = {"t": ("+" if gap > 0 else "") + numfmt.format_value(gap, "0", loc), "v": gap, "k": "n"}
                if abs(gap) >= 0.5:
                    gap_cell["c"] = "pos" if gap > 0 else "neg"
                sq = self._rv_quote(calc, si, r)
                if sq["stale"]:                              # the screen's yield is no live quote's
                    gap_cell = self._soft(gap_cell, "Ekranda iki taraflı canlı kota yok (%s): ekran getirisi bu fiyattan" % sq["status"])
            mid_cell = {"t": numfmt.format_value(mid, "0.00", loc), "v": mid, "k": "n"} if mid is not None else {"t": "", "k": ""}
            has_fresh = bool(fresh) or any(type(q.get(k)) is float for k in ("best_bid", "best_ask"))
            if mid is None and not has_fresh and (q.get("brokers") or any(type(q.get(k)) is float for k in ("last", "level"))):
                # what the brokers said is all stale: no yield, no distance from the screen - said so
                mid_cell = {"t": "bayat", "k": "s", "al": "c", "cls": "stale soft",
                            "tip": "Taze broker kotası yok (bayat sınırı %d dk): getiri ve ekran farkı yalnız taze kotadan" % stale_min}
            rows[i].extend(self._bond_cells(q, loc) + [mid_cell, gap_cell])
        # ▸: the bond's card
        for i, r in enumerate(rnums):
            v = calc.get(si, r, 1) if 5 <= r <= 54 else None
            code = "".join(str(v).split()).upper() if isinstance(v, str) else ""
            if r == 4:
                rows[i].append({"t": "Kart", "k": "s", "b": 1, "f": "hd", "tip": "Kâğıdın bütün bilgisi tek pencerede"})
            else:
                rows[i].append({"t": "▸", "k": "s", "cls": "act cardlink", "tip": "Kâğıt kartı: " + code} if code else {"t": "", "k": ""})
        data["c"] = list(data.get("c") or []) + [h for h, _ in heads] + ["Kart"]
        data["added"] = int(data.get("added") or 0) + len(heads) + 1

    # ================================================================== live quotes: the sizes of the orders
    #: DİBS RV's columns worked out of the clean price in use (their headers start so): soft while no live quote
    #: stands behind that price
    _RV_PRICED = ("BIST basit getiri", "BIST bileşik getiri", "Getiri − OIS", "ASW (S/B)", "Pahalı/ucuz", "Sinyal", "ASW FX")

    @staticmethod
    def _rv_quote(calc, si: int, r: int) -> Dict[str, Any]:
        """What the sizes say of a row of DİBS RV: the size of its bid and ask (0: no order stands; not a number:
        not known), Bloomberg's figures (FD / FE), and ``stale``: both sizes known and not both sides live - the
        price in use and what the row works out of it rest on no live quote (``tip`` says so)."""
        def v(col: str) -> Any:
            return calc.get(si, r, parse_a1("%s1" % col) % COLS)
        b, a = v(ex.RV_SIZE[0]), v(ex.RV_SIZE[1])
        stale = type(b) is float and type(a) is float and not (b > 0 and a > 0)
        status = v("J")
        status = status if isinstance(status, str) else ""
        tip = "Fiyat durumu: %s · iki taraflı canlı kota yok, değer bu fiyattan" % status if stale else ""
        return {"bid": b, "ask": a, "raw_bid": v("FD"), "raw_ask": v("FE"), "stale": stale, "status": status, "tip": tip}

    @staticmethod
    def _quote_cell(cell: Dict[str, Any], size: Any, figure: Any, side: str, loc) -> Dict[str, Any]:
        """A bid / ask as a page shows it: "–" (soft) where the sheet says no order stands, Bloomberg's figure in
        the tip; a live quote with its size in the tip; anything else as it is."""
        if str(cell.get("t") or "").strip() == ex.NO_QUOTE:
            tip = "Kota yok: %s tarafında emir yok (%s boş)" % (side, "BID_SIZE" if side == "bid" else "ASK_SIZE")
            if type(figure) is float and figure > 0:
                tip += " · Bloomberg'in tekrar ettiği fiyat %s, canlı değil" % numfmt.format_value(figure, "0.000", loc)
            return {"t": ex.NO_QUOTE, "k": "s", "al": "r", "cls": "soft", "tip": tip}
        if type(size) is float and size > 0 and str(cell.get("t") or "").strip():
            line = "%s boyutu: %s" % (side.capitalize(), numfmt.format_value(size, ex.INT0, loc))
            return dict(cell, tip=cell["tip"] + "\n" + line if cell.get("tip") else line)
        return cell

    @staticmethod
    def _soft(cell: Dict[str, Any], tip: str) -> Dict[str, Any]:
        """A value worked out of a price that is no live quote: soft, the reason in the tip."""
        if not str(cell.get("t") or "").strip():
            return cell
        return dict(cell, cls=((cell.get("cls") or "") + " soft").strip(), tip=cell["tip"] + "\n" + tip if cell.get("tip") else tip)

    def _rv_priced_cols(self, book) -> List[str]:
        """DİBS RV's columns (letters) worked out of the price in use (:attr:`_RV_PRICED`)."""
        sh = book.model.sheets[book.model.sheet_index["DİBS RV"]]
        return [index_to_col(c) for c in range(1, sh.max_col + 1)
                if isinstance(sh.consts.get(4 * COLS + c), str) and sh.consts[4 * COLS + c].strip().startswith(self._RV_PRICED)]

    def _rv_quote_marks(self, book, calc, si: int, data: Dict[str, Any], loc) -> None:
        """The DİBS RV page: its bid / ask ("–" where no order stands, the size of a live one in the tip) and, on a
        row whose price is no live quote, what it works out of that price soft."""
        rows, rnums, cols = data.get("rows") or [], data.get("r") or [], list(data.get("c") or [])
        at = {c: cols.index(c) for c in ["K", "L"] + self._rv_priced_cols(book) if c in cols}
        for i, r in enumerate(rnums):
            if not ex.LIVE_FIRST <= r <= ex.LIVE_LAST or not calc.get(si, r, 1):
                continue
            q = self._rv_quote(calc, si, r)
            for col, j in at.items():
                if j >= len(rows[i]):
                    continue
                if col in ("K", "L"):
                    side = "bid" if col == "K" else "ask"
                    rows[i][j] = self._quote_cell(rows[i][j], q[side], q["raw_" + side], side, loc)
                elif q["stale"]:
                    rows[i][j] = self._soft(rows[i][j], q["tip"])

    def _dibs_live_columns(self, book, user: Optional[str], data: Dict[str, Any], loc) -> None:
        """The DİBS Canlı table, completed: the last trade of each value date at the time the dashboard saw it
        (live: its last price changed or its volume grew today) instead of Bloomberg's day of the last trade, and
        the day's Broker Chat board on the right."""
        sheet = ex.LIVE_SHEET
        rows, rnums, cols = data.get("rows") or [], data.get("r") or [], list(data.get("c") or [])
        if not rows or sheet not in book.model.sheet_index:
            return
        si = book.model.sheet_index[sheet]
        calc = self._calc(user, book)
        layout = ex._live_cols()
        said = self._board_bonds(user)
        where = {g["when"]: (cols.index(g["when"]), layout["sec"][k]) for k, g in enumerate(layout["groups"]) if g["when"] in cols}
        # each value date's bid / ask and the extra source's: (visible column, size, Bloomberg's figure, side)
        quotes = [(g[side], layout["size"][k][side], layout["raw"][k][side], side)
                  for k, g in enumerate(layout["groups"]) for side in ("bid", "ask")]
        quotes += [(col, layout["size_extra"][side], layout["raw_extra"][side], side)
                   for col, side in ((ex.LIVE_EXTRA, "bid"), (index_to_col(ex._col(ex.LIVE_EXTRA) + 1), "ask"))]
        quotes = [x for x in quotes if x[0] in cols]
        for i, r in enumerate(rnums):
            if r == 4:
                rows[i].extend([{"t": t, "k": "s", "b": 1, "f": "hd", "tip": tip} for t, tip in self._BOARD_HEADS]
                               + [{"t": "Kart", "k": "s", "b": 1, "f": "hd", "tip": "Kâğıdın bütün bilgisi tek pencerede"}])
                continue
            if not ex.LIVE_FIRST <= r <= ex.LIVE_LAST:
                rows[i].extend([{"t": "", "k": ""} for _ in range(len(self._BOARD_HEADS) + 1)])
                continue
            isin = calc.get(si, r, 1)
            isin = "".join(str(isin).split()).upper() if isinstance(isin, str) else ""
            for col, (j, sec_col) in where.items():
                sec = calc.get(si, r, parse_a1("%s1" % sec_col) % COLS)
                seen = self.trades_seen(sec) if isinstance(sec, str) and sec else None
                if seen and j < len(rows[i]):
                    cell = dict(rows[i][j])
                    was = cell.get("t") or ""
                    cell.update({"t": "bugün " + seen["time"], "k": "s", "cls": "fresh",
                                 "tip": "Dashboard'un bu kâğıtta işlem gördüğü an: %s %s"
                                        % ("son fiyat" if seen.get("by") == "LAST_PRICE" else "hacim arttı", seen["time"])
                                        + (" · fiyat %s" % numfmt.format_value(seen["price"], "0.000", loc) if type(seen.get("price")) is float else "")
                                        + (" · Bloomberg son işlem günü: %s" % was if was else "")})
                    rows[i][j] = cell
            if isin:
                for col, size, raw, side in quotes:
                    j = cols.index(col)
                    if j < len(rows[i]):
                        rows[i][j] = self._quote_cell(rows[i][j], calc.get(si, r, parse_a1("%s1" % size) % COLS),
                                                      calc.get(si, r, parse_a1("%s1" % raw) % COLS), side, loc)
            rows[i].extend(self._bond_cells(said.get(isin) if isin else None, loc))
            rows[i].append({"t": "▸", "k": "s", "cls": "act cardlink", "tip": "Kâğıt kartı: " + isin} if isin else {"t": "", "k": ""})
        data["c"] = cols + [h for h, _ in self._BOARD_HEADS] + ["Kart"]
        data["added"] = int(data.get("added") or 0) + len(self._BOARD_HEADS) + 1

    def _live_securities(self, user: Optional[str], book) -> Dict[str, Tuple[str, str, str]]:
        """The securities of the DİBS Canlı sheet: Bloomberg security -> (ISIN, value date caption, source)."""
        out: Dict[str, Tuple[str, str, str]] = {}
        if ex.LIVE_SHEET not in book.model.sheet_index:
            return out
        si = book.model.sheet_index[ex.LIVE_SHEET]
        calc = self._calc(user, book)
        layout = ex._live_cols()
        for r in range(ex.LIVE_FIRST, ex.LIVE_LAST + 1):
            isin = calc.get(si, r, 1)
            if not isinstance(isin, str) or not isin:
                continue
            for k, g in enumerate(layout["groups"]):
                sec = calc.get(si, r, parse_a1("%s1" % layout["sec"][k]) % COLS)
                src = calc.get(si, *divmod(parse_a1(g["src"]), COLS))
                if isinstance(sec, str) and sec:
                    out[sec] = (isin, g["cap"], str(src or ""))
        return out

    def _dibs_tape(self, user: Optional[str], loc, isin: Optional[str] = None) -> List[Dict[str, Any]]:
        """Today's bond trades, newest first: the ones said in the Broker Chat (time, bond, price, the yield it
        stands for, the side taken, the value date, who said it) and - live - the ones the dashboard saw on
        Bloomberg (a value date's last price changed or its volume grew).  ``isin``: one bond only."""
        from . import bonds as bd
        today = self.today_iso()
        rows, _, _ = self._broker_board(user, today, today)
        trades = [q for q in rows if q.get("ok") and q.get("product") == "DIBS" and q.get("event") == "trade"
                  and q.get("kind") != "switch" and (isin is None or q.get("isin") == isin)]
        self._bond_implied(user, trades)
        out: List[Dict[str, Any]] = []
        for q in trades:
            imp = (q.get("implied") or {}).get("price") if q.get("unit") == "px" else q.get("price")
            out.append({"time": q.get("time") or "", "isin": q.get("isin") or "", "label": q.get("label") or "",
                        "price": q.get("price"), "unit": q.get("unit") or "px", "yield": imp if type(imp) is float else None,
                        "side": q.get("side") or "", "settle": q.get("settle") or "", "flags": list(q.get("flags") or []),
                        "who": ("Biz" if q.get("party") == "biz" else (q.get("source") or "Broker"))
                               + (" · " + q["sender"] if q.get("sender") else ""), "note": q.get("note") or "", "from": "chat"})
        book = self.books.get("tto")
        if book is not None and self._trades_day == today and self._trades_seen:
            for sec, (code, cap, src) in self._live_securities(user, book).items():
                seen = self._trades_seen.get(sec)
                if not seen or (isin is not None and code != isin):
                    continue
                b = bd.by_isin(code)
                out.append({"time": seen["time"], "isin": code, "label": bd.short_label(b) if b else code,
                            "price": seen.get("price"), "unit": "px",            # Borsa İstanbul trades on the price
                            "yield": None, "side": "", "settle": cap, "flags": [],
                            "who": "Bloomberg · " + src, "note": "son fiyat değişti" if seen.get("by") == "LAST_PRICE" else "hacim arttı",
                            "from": "bloomberg"})
        out.sort(key=lambda x: x["time"], reverse=True)
        return out

    def _tape_table(self, user: Optional[str], loc) -> Dict[str, Any]:
        """The tape as a table of the page (generated, no cell of a sheet)."""
        heads = ["Saat", "Kâğıt", "ISIN", "Fiyat", "Getiri %", "Taraf", "Valör", "Kim", "Not", "Kart"]
        rows = [[{"t": x, "k": "s", "b": 1, "f": "hd"} for x in heads]]
        for x in self._dibs_tape(user, loc):
            px = x["price"]
            side = {"ask": "offer alındı", "bid": "bid'e verildi"}.get(x["side"], "")
            rows.append([
                {"t": x["time"], "k": "s"}, {"t": x["label"], "k": "s", "b": 1}, {"t": x["isin"], "k": "s", "cls": "soft"},
                {"t": numfmt.format_value(px, "0.000" if x["unit"] == "px" else "0.00", loc), "v": px, "k": "n",
                 "cls": "buy" if x["side"] == "ask" else ("sell" if x["side"] == "bid" else "")} if type(px) is float else {"t": "", "k": ""},
                {"t": numfmt.format_value(x["yield"], "0.00", loc), "v": x["yield"], "k": "n", "cls": "soft"}
                if type(x["yield"]) is float else {"t": "", "k": ""},
                {"t": side, "k": "s"}, {"t": x["settle"], "k": "s"},
                {"t": x["who"], "k": "s", "cls": "soft" if x["from"] == "bloomberg" else ""},
                {"t": x["note"], "k": "s", "cls": "soft"},
                {"t": "▸", "k": "s", "cls": "act cardlink", "tip": "Kâğıt kartı: " + x["isin"]} if x["isin"] else {"t": "", "k": ""}])
        if len(rows) == 1:
            rows.append([{"t": "Bugün henüz DİBS işlemi yok (Broker Chat'te söylenen ya da canlıda Bloomberg'de görülen)", "k": "s",
                          "cls": "soft", "cs": len(heads)}] + [{"t": "", "k": ""} for _ in heads[1:]])
        return {"rows": rows, "r": list(range(1, len(rows) + 1)), "c": [index_to_col(k + 1) for k in range(len(heads))],
                "added": len(heads), "tape": True}

    def bond_card(self, user: Optional[str], isin: str) -> Dict[str, Any]:
        """Everything the dashboard has on one bond: what it is (the catalog), its row of DİBS RV (yield, ASW,
        signal, duration, DV01, carry), its prices on each value date with the last trades, the implied repo,
        today's Broker Chat board and lines, and its trades of the day."""
        return self.et.call(self._bond_card, user, isin)

    def _bond_card(self, user, isin) -> Dict[str, Any]:
        from . import bonds as bd
        code = "".join(str(isin or "").split()).upper()
        if not code:
            raise ServiceError("ISIN gerekli")
        loc = numfmt.get_locale(self.settings.locale)
        b = bd.by_isin(code)
        out: Dict[str, Any] = {"isin": code, "known": b is not None, "label": bd.short_label(b) if b else code,
                               "kind": (b or {}).get("kind"), "kind_text": bd.KINDS.get((b or {}).get("kind"), ""),
                               "coupon": (b or {}).get("coupon"), "maturity": (b or {}).get("maturity"), "name": (b or {}).get("name") or ""}
        if b:
            mat = _dt.date.fromisoformat(b["maturity"])
            today = _dt.date.fromisoformat(self.today_iso())
            out["days"] = (mat - today).days
            out["years"] = round(out["days"] / 365.25, 2)
        book = self.books.get("tto")
        out["rv"], out["live"], out["repo"] = [], [], []
        if book is not None:
            calc = self._calc(user_key(user) if user else None, book)
            R = self.renderers[book.id]
            info = bl.bond_info(book, calc, code)
            if info and "".join(str(info.get("isin") or "").split()).upper() == code:
                si = book.model.sheet_index["DİBS RV"]
                sh = book.model.sheets[si]
                want = ("Tip", "Kupon", "Fiyat durumu", "Kullanılan temiz", "Valör", "Kirli", "BIST bileşik getiri", "Alış−satış",
                        "Getiri − OIS", "ASW (S/B)", "Uydurulmuş ASW (bp)", "Pahalı/ucuz (bp", "Sinyal", "ASW FX swap", "Pahalı/ucuz FX",
                        "Mod. süre", "DV01 TL", "C+R (bp)", "Son işlem tarihi", "Son işlem fiyatı", "Bugün düşük", "Bugün yüksek")
                q = self._rv_quote(calc, si, info["row"])
                for c in range(1, sh.max_col + 1):
                    cap = sh.consts.get(4 * COLS + c)
                    if isinstance(cap, str) and any(cap.strip().startswith(w) for w in want):
                        cell = R.cell(calc, si, info["row"], c, loc)
                        if str(cell.get("t") or "").strip():
                            item = {"name": cap.strip(), "t": cell.get("t"), "c": cell.get("c")}
                            if q["stale"] and cap.strip().startswith(self._RV_PRICED):      # worked out of no live quote
                                item.update(soft=True, tip=q["tip"])
                            out["rv"].append(item)
                out["row"] = info["row"]
            if ex.LIVE_SHEET in book.model.sheet_index:
                si = book.model.sheet_index[ex.LIVE_SHEET]
                layout = ex._live_cols()
                row = next((r for r in range(ex.LIVE_FIRST, ex.LIVE_LAST + 1) if calc.get(si, r, 1) == code), None)
                if row is not None:
                    def txt(addr: str) -> str:
                        r0, c0 = divmod(parse_a1(addr), COLS)
                        return str(R.cell(calc, si, r0, c0, loc).get("t") or "")

                    def quote(col: str, size: str, raw: str, side: str) -> Dict[str, str]:
                        """A bid / ask: the price or "–" (``_tip`` says why), the size of a live quote."""
                        s = calc.get(si, row, parse_a1("%s1" % size) % COLS)
                        got = self._quote_cell({"t": txt("%s%d" % (col, row))}, s, calc.get(si, row, parse_a1("%s1" % raw) % COLS), side, loc)
                        return {side: got["t"], side + "_size": numfmt.format_value(s, ex.INT0, loc) if type(s) is float and s > 0 else "",
                                side + "_tip": (got.get("tip") or "") if got["t"] == ex.NO_QUOTE else ""}

                    for k, g in enumerate(layout["groups"]):
                        sec = calc.get(si, row, parse_a1("%s1" % layout["sec"][k]) % COLS)
                        seen = self.trades_seen(sec) if isinstance(sec, str) else None
                        item = {"cap": g["cap"], "src": txt(g["src"]), "date": txt(g["date"]),
                                "last": txt("%s%d" % (g["last"], row)), "when": txt("%s%d" % (g["when"], row)),
                                "vol": txt("%s%d" % (g["vol"], row)), "seen": seen["time"] if seen else ""}
                        for side in ("bid", "ask"):
                            item.update(quote(g[side], layout["size"][k][side], layout["raw"][k][side], side))
                        out["live"].append(item)
                    w, x, y = ex.LIVE_REPO
                    for name, col in (("T0→T1 repo %", w), ("T1→T2 repo %", x), ("T0→T1 − TLREF (bp)", y)):
                        out["repo"].append({"name": name, "t": txt("%s%d" % (col, row))})
                    out["repo_note"] = self._repo_note(txt, layout, row)
                    extra = ex.LIVE_EXTRA
                    out["extra"] = {"src": txt("%s2" % extra)}
                    for col, side in ((extra, "bid"), (index_to_col(ex._col(extra) + 1), "ask")):
                        out["extra"].update(quote(col, layout["size_extra"][side], layout["raw_extra"][side], side))
        board = self._board_bonds(user).get(code)
        out["board"] = None
        if board is not None:
            # the board's rules: the best fresh bid and offer, a stale one greyed with its broker and age, the yields
            # of the fresh ones only
            cells = self._bond_cells(board, loc)
            imp = board.get("implied") or {}
            implied = {k: v for k, v in (("bid", imp.get("best_bid")), ("ask", imp.get("best_ask")),
                                         ("last", imp.get("last") if not board.get("last_stale") else None)) if type(v) is float}
            if implied and type(imp.get("screen_yield")) is float:
                implied["screen_yield"] = imp["screen_yield"]
            out["board"] = {"bid": cells[0]["t"], "ask": cells[1]["t"], "last": cells[2]["t"], "who": cells[3]["t"],
                            "stale": {k: "stale" in (c.get("cls") or "") for k, c in zip(("bid", "ask", "last", "who"), cells)},
                            "tips": {k: c.get("tip") or "" for k, c in zip(("bid", "ask", "last", "who"), cells)},
                            "implied": implied}
        today = self.today_iso()
        lines = [q for q in self.store.broker_quotes(today, today) if q.get("ok") and q.get("isin") == code]
        people = self._people()
        # each quote line of the chat: does it still stand on the board (fresh, or stale), or is it gone - said again,
        # withdrawn, traded away, or before a reset
        stands: Dict[Any, bool] = {}
        for b in (board or {}).get("brokers") or []:
            for side in ("bid", "ask"):
                if b.get(side + "_id") is not None:
                    stands[b[side + "_id"]] = stands.get(b[side + "_id"], True) and bool(b.get(side + "_stale"))
        now = _dt.datetime.now()
        out["chat"] = []
        for q in lines:
            source, party = self._who(people, q, q.get("source") or "", q.get("party") or "")
            state = None
            if q.get("event") == "quote":
                if party == "biz":
                    mine = board is not None and q.get("id") is not None and q["id"] in (board.get("our_bid_id"), board.get("our_ask_id"))
                    state = ("stale" if board.get("our_stale") else "fresh") if mine else "gone"
                else:
                    state = ("stale" if stands[q["id"]] else "fresh") if q.get("id") in stands else "gone"
            out["chat"].append({"time": q.get("time"), "who": ("Biz" if party == "biz" else (source or "Broker"))
                                + (" · " + q["sender"] if q.get("sender") else ""), "raw": q.get("raw") or "",
                                "event": q.get("event"), "side": q.get("side"), "bid": q.get("bid"), "ask": q.get("ask"),
                                "price": q.get("price"), "unit": q.get("unit"), "state": state,
                                "age": self._age_text(bc.line_age(q, now)) if state in ("fresh", "stale") else ""})
        out["tape"] = self._dibs_tape(user, loc, code)
        return out

    # ================================================================== the order of the pricing sources
    def sources(self) -> Dict[str, Any]:
        """The pricing sources of the live curves, in the order they are tried (settings -> data sources), and
        the source each quoted tenor is read from right now."""
        book = self.books.get("tto")
        if book is None or ex.SRC_SHEET not in book.model.sheet_index:
            return {"available": False, "curves": [], "rows": [], "live": self.mode == "live"}

        def run():
            calc = self._calc(None, book)
            si = book.model.sheet_index[ex.SRC_SHEET]

            def get(addr):
                v = calc.get(si, *divmod(parse_a1(addr), COLS))
                if isinstance(v, bool) or v is None:
                    return v
                return v if isinstance(v, (int, float, str)) else str(v)

            curves = []
            for kind, title, row, first, fallback in ex.SRC_LISTS:
                codes = [str(get("%s%d" % (c, row)) or "").strip().upper() for c in ex.SRC_COLS]
                curves.append({"id": kind, "title": title, "sources": [c for c in codes if c], "default": [first],
                               "fallback": fallback})
            rows = []
            k = ex.SRC_FIRST
            kinds = {c["title"]: c["id"] for c in curves}
            while get("A%d" % k) in kinds:
                kind = kinds[get("A%d" % k)]
                rank = get("F%d" % k)
                rows.append({"curve": kind, "tenor": get("B%d" % k), "excel": get("C%d" % k), "source": get("D%d" % k),
                             "ticker": get("E%d" % k), "rank": int(rank) if isinstance(rank, float) else None,
                             "bid": get("I%d" % k), "ask": get("J%d" % k) if kind != "ois" else None})
                k += 1
            return {"available": True, "curves": curves, "rows": rows, "live": self.mode == "live", "gen": self.gen}

        return self.et.call(run)

    def set_sources(self, user: str, lists: Dict[str, Any]) -> Dict[str, Any]:
        """A new order of pricing sources for a curve (or for several): ``{"ois": ["GFOF", "BGN"], ...}`` - up to
        four Bloomberg pricing source codes each; the workbook's own ticker is always tried last.  For everyone,
        live at once, and the history follows (the new tickers' closes are fetched)."""
        user = self.require_user(user)
        if ex.SRC_SHEET not in self.books["tto"].model.sheet_index:
            raise ServiceError("bu dosyada kaynak sayfası yok")
        items = []
        for kind, title, row, first, fallback in ex.SRC_LISTS:
            codes = lists.get(kind) if isinstance(lists, dict) else None
            if codes is None:
                continue
            if isinstance(codes, str):
                codes = re.split(r"[\s,;>→]+", codes)
            clean: List[str] = []
            for c in codes:
                c = re.sub(r"\s+", "", str(c or "")).upper()
                if not c:
                    continue
                if not re.match(r"^[A-Z0-9]{2,8}$", c):
                    raise ServiceError("%s: kaynak kodu anlaşılamadı – %s (Bloomberg fiyat kaynağı: GFOF, ICPL, BGN, CMPN …)" % (title, c))
                if c not in clean:
                    clean.append(c)
            if len(clean) > len(ex.SRC_COLS):
                raise ServiceError("%s: en fazla %d kaynak" % (title, len(ex.SRC_COLS)))
            for n, col in enumerate(ex.SRC_COLS):
                items.append({"ref": "%s!%s%d" % (ex.SRC_SHEET, col, row), "value": clean[n] if n < len(clean) else ""})
        if not items:
            raise ServiceError("değişiklik yok")
        res = self.set_inputs(user, "tto", items)
        if res["errors"]:
            raise ServiceError("; ".join(res["errors"]))
        hist = getattr(self, "history", None)
        if hist is not None:
            try:
                hist.kick()                         # the closes of the new tickers
            except Exception:  # noqa: BLE001
                pass
        return self.sources()

    def market_unknown(self) -> Dict[str, Any]:
        """What Bloomberg said it does not know - securities, fields - grouped by the shape of the ticker, with
        the cells of the workbooks that ask for them.  The answer to "N ticker Bloomberg'de yok"."""
        from .marketdata.bloomberg import api_security
        prov = self.provider
        try:
            answers = prov.unknown() if hasattr(prov, "unknown") else []
        except Exception:  # noqa: BLE001
            answers = []
        callers = self._market_callers() if answers else {}
        places = self._cell_places()
        rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for key, answer in answers:
            kind = key[0]
            sec = str(key[2] if kind == "RT" else key[1])
            field = str(key[3] if kind == "RT" else (key[2] if len(key) > 2 else ""))
            code, text = self._ANSWERS.get(answer, ("na", answer))
            row = rows.get((sec, code))
            if row is None:
                row = rows[(sec, code)] = {"security": sec, "api": api_security(sec) if kind in ("BDP", "BDS", "BDH") else sec,
                                           "answer": code, "answer_text": text, "fields": [], "kinds": [], "cells": [], "ncells": 0,
                                           "_seen": set()}
            if field and field not in row["fields"]:
                row["fields"].append(field)
            if kind not in row["kinds"]:
                row["kinds"].append(kind)
            for bid, si, rc in callers.get(key, ()):
                if (bid, si, rc) in row["_seen"]:
                    continue
                row["_seen"].add((bid, si, rc))
                row["ncells"] += 1
                if len(row["cells"]) >= 6:
                    continue
                book = self.books[bid]
                sheet = book.model.sheets[si].name
                r, c = divmod(rc, COLS)
                page = next(((pg, pn) for r1, c1, r2, c2, pg, pn in places.get((bid, sheet), ())
                             if r1 <= r <= r2 and c1 <= c <= c2), (None, None))
                row["cells"].append({"book": bid, "book_title": book.title, "sheet": sheet, "ref": a1(rc), "page": page[0],
                                     "panel": page[1]})
        out_rows = sorted(rows.values(), key=lambda x: ({"security": 0, "field": 1}.get(x["answer"], 2), x["security"]))
        groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for row in out_rows:
            row.pop("_seen", None)
            # the shape of the ticker: numbers become "#", a pricing source with no code in front of it "@…"
            pattern = re.sub(r"^@\S+", "@…", re.sub(r"\d+", "#", row["security"]).strip()) or "(boş)"
            g = groups.get((pattern, row["answer"]))
            if g is None:
                note = next((n for rx, n in self._UNKNOWN_NOTES if rx.search(row["security"])), "")
                g = groups[(pattern, row["answer"])] = {"pattern": pattern, "answer": row["answer"], "answer_text": row["answer_text"],
                                                        "count": 0, "examples": [], "numbers": [], "fields": [], "where": {},
                                                        "note": note}
            g["count"] += 1
            if len(g["examples"]) < 4:
                g["examples"].append(row["security"])
            g["numbers"].append([int(x) for x in re.findall(r"\d+", row["security"])][:3])
            for f in row["fields"]:
                if f not in g["fields"]:
                    g["fields"].append(f)
            for cl in row["cells"]:
                w = g["where"].setdefault((cl["book_title"], cl["sheet"], cl["page"]), 0)
                g["where"][(cl["book_title"], cl["sheet"], cl["page"])] = w + 1
        out_groups = []
        for g in sorted(groups.values(), key=lambda x: (-x["count"], x["pattern"])):
            g["numbers"] = self._number_ranges(g.pop("numbers"))
            g["where"] = [{"book_title": b, "sheet": sh, "page": pg} for (b, sh, pg), _n in
                          sorted(g["where"].items(), key=lambda kv: -kv[1])]
            if not g["note"] and g["where"] and all(w["sheet"] == ex.SRC_SHEET for w in g["where"]):
                g["note"] = self._SOURCE_NOTE           # a source of the source order that has no such ticker
            out_groups.append(g)
        st = {}
        try:
            st = prov.status() or {}
        except Exception:  # noqa: BLE001
            pass
        return {"mode": self.mode, "securities": sum(1 for r in out_rows if r["answer"] == "security"),
                "fields": sum(1 for r in out_rows if r["answer"] != "security"), "groups": out_groups, "rows": out_rows,
                "subscriptions_invalid": st.get("subscriptions_invalid"), "gen": self.gen}

    @staticmethod
    def _number_ranges(numbers: List[List[int]]) -> str:
        """The numbers that vary inside a group of tickers, as ranges: "3–400 · 0–1"."""
        if len(numbers) < 2:
            return ""
        width = min(len(n) for n in numbers)
        parts = []
        for k in range(width):
            vals = sorted({n[k] for n in numbers})
            if len(vals) < 2:
                continue
            parts.append("%d–%d (%d farklı)" % (vals[0], vals[-1], len(vals)) if len(vals) > 2 else "%d, %d" % (vals[0], vals[1]))
        return " · ".join(parts)

    def market_unknown_export(self) -> Tuple[bytes, str]:
        """The list as an .xlsx file: the groups, and every ticker with the cells that ask for it."""
        from .xlsx import XlsxBook
        data = self.market_unknown()
        wb = XlsxBook()
        ws = wb.add_sheet("Gruplar")
        ws.row(1, 1, ["Kalıp", "Adet", "Bloomberg'in cevabı", "Sayılar", "Alanlar", "Örnekler", "Nerede", "Açıklama"], bold=True, fill="E7E6E6")
        for i, g in enumerate(data["groups"]):
            ws.row(2 + i, 1, [g["pattern"], g["count"], g["answer_text"], g["numbers"], ", ".join(g["fields"]), ", ".join(g["examples"]),
                              "; ".join("%s · %s" % (w["book_title"], w["sheet"]) for w in g["where"]), g["note"]])
        ws.autosize()
        ls = wb.add_sheet("Liste")
        ls.row(1, 1, ["Ticker", "API'ye giden", "Bloomberg'in cevabı", "Alanlar", "Çağrı", "Çalışma kitabı", "Sayfa", "Hücreler", "Hücre sayısı"],
               bold=True, fill="E7E6E6")
        for i, r in enumerate(data["rows"]):
            first = r["cells"][0] if r["cells"] else {}
            ls.row(2 + i, 1, [r["security"], r["api"], r["answer_text"], ", ".join(r["fields"]), ", ".join(r["kinds"]),
                              first.get("book_title", ""), first.get("sheet", ""), ", ".join(c["ref"] for c in r["cells"]), r["ncells"]])
        ls.autosize()
        return wb.to_bytes(), "Bloomberg_tanimsiz_%s.xlsx" % _dt.date.today().strftime("%Y.%m.%d")

    # ================================================================== realized volatility · carry against it
    def _vol_curves(self) -> Tuple[Dict[str, Dict[str, Dict[str, float]]], Dict[str, Dict[str, float]], Dict[str, Any]]:
        """The daily closes the history keeps, by product (OIS, XCCY) and tenor, and what they cover."""
        mark = (self.history.rev, self.gen)
        hit = getattr(self, "_vol_cache", None)
        if hit is not None and hit[0] == mark:
            return hit[1]
        out = self._vol_read()
        self._vol_cache = (mark, out)
        return out

    def _vol_read(self) -> Tuple[Dict[str, Dict[str, Dict[str, float]]], Dict[str, Dict[str, float]], Dict[str, Any]]:
        from .history import source_text
        snap = self.history.snapshot()
        defs = [d for d in snap["defs"] if (d.group in ("ois", "xccy", "off") and d.months) or d.group == "dibs"]
        start = (snap["today"] - _dt.timedelta(days=600)).isoformat()
        data = self.store.hist_many([i for d in defs for i in d.ids()], start)
        curves: Dict[str, Dict[str, Dict[str, float]]] = {p: {} for p in vc.PRODUCTS}
        months: Dict[str, Dict[str, float]] = {p: {} for p in vc.PRODUCTS}
        for d in defs:
            product = {"ois": "OIS", "dibs": "DIBS"}.get(d.group, "XCCY")
            label = d.label.strip().upper()
            points = d.pick(data)[1]
            if product == "XCCY" and curves[product].get(label):
                continue                                    # the swap itself goes before an implied rate of the same tenor
            curves[product][label] = points
            # a bond has no tenor to sort by; a floater is followed by its price, not a yield ("px")
            months[product][label] = d.months if product != "DIBS" else (-1.0 if d.unit == "px" else 0.0)
        days = sorted({day for series in curves["OIS"].values() for day in series})
        info = {"first": days[0] if days else None, "last": days[-1] if days else None, "days": len(days),
                "source": source_text(snap), "live": self.mode == "live",
                "tenors": {p: sorted((t for t, s in curves[p].items() if s), key=lambda t: months[p][t]) for p in vc.PRODUCTS}}
        return curves, months, info

    def vol(self, user: Optional[str], text: str, window: Any = 20) -> Dict[str, Any]:
        """Realized volatility of the instruments typed (one per line or separated by commas), from the daily
        closes of the history: bp a day over the last 10 / 20 / 60 / 120 / 250 changes."""
        try:
            window = int(window)
        except (TypeError, ValueError):
            window = 20
        if window not in vc.WINDOWS:
            window = 20
        items = vc.parse_items(str(text or "")[:4000])[:40]
        curves, months, info = self._vol_curves()
        rows = []
        for it in items:
            if not it["ok"]:
                rows.append(it)
                continue
            product = it["product"] if it["product"] in curves else "OIS"
            if product == "DIBS" and months[product].get(it["tenors"][0]) == -1.0:
                it["unit"] = "px"                           # the price of a floater: moves in points, not bp
            rows.append(vc.describe(it, curves[product], months[product], window))
        return {"rows": rows, "window": window, "windows": list(vc.WINDOWS), "year": vc.YEAR, "history": info}

    # ================================================================== Spot / FX and FX vol
    def _fx(self, fn, *args):
        from .fx import FxError
        try:
            return fn(*args)
        except FxError as exc:
            raise ServiceError(str(exc))

    def fx_board(self, user: Optional[str]) -> Dict[str, Any]:
        """Every pair's spot and its main vols (the Spot / FX page's table)."""
        return self._fx(self.fx.board, self.require_user(user))

    def fx_surface(self, user: Optional[str], pair: Any, model: Any = "svi", levels: Any = None) -> Dict[str, Any]:
        """One pair: quotes, forwards, smiles, the distribution of the spot by tenor and the probability matrix."""
        lv = levels if isinstance(levels, list) else None
        return self._fx(self.fx.surface, self.require_user(user), str(pair or "USDTRY"), str(model or "svi"), lv)

    def fx_override(self, user: Optional[str], pair: Any, tenor: Any, kind: Any, value: Any) -> Dict[str, Any]:
        """A quote of one's own in place of Bloomberg's (``value`` empty: back to Bloomberg) - seen by its owner only."""
        out = self._fx(self.fx.set_override, self.require_user(user), str(pair or ""), str(tenor or ""), str(kind or ""), value)
        self.bump()
        return out

    def fx_override_clear(self, user: Optional[str], pair: Any) -> Dict[str, Any]:
        out = self._fx(self.fx.clear_overrides, self.require_user(user), str(pair or ""))
        self.bump()
        return out

    def fx_monitor(self, user: Optional[str], window: Any = 250) -> Dict[str, Any]:
        """The vol monitor: every pair's core vols, their changes and where they stand; the desk's own tickers."""
        return self._fx(self.fx.monitor, self.require_user(user), window)

    def fx_pair(self, user: Optional[str], pair: Any, tenor: Any = "1M", model: Any = "svi") -> Dict[str, Any]:
        """One pair of the vol monitor in depth: term structure, skew and smile now / a week / a month ago, history."""
        return self._fx(self.fx.pair_detail, self.require_user(user), str(pair or "USDTRY"), str(tenor or "1M"),
                        str(model or "svi"))

    def fx_series(self, user: Optional[str], ticker: Any, window: Any = 250, pair: Any = None, kind: Any = None,
                  tenor: Any = None) -> Dict[str, Any]:
        """The closes of a ticker, or of a pair's quote / skew by kind and tenor (a picked row or cell)."""
        self.require_user(user)
        return self._fx(self.fx.series, str(ticker or ""), window, pair or None, kind, tenor)

    def fx_tenor(self, user: Optional[str], pair: Any, tenor: Any) -> Dict[str, Any]:
        """One tenor of a pair through time: its five quotes and its skew (a row of the surface clicked)."""
        return self._fx(self.fx.tenor_history, self.require_user(user), str(pair or "USDTRY"), str(tenor or ""))

    def fx_tickers(self, user: Optional[str]) -> Dict[str, Any]:
        self.require_user(user)
        return {"items": self.fx.user_tickers(), "settings": self.fx.settings()}

    def fx_ticker_add(self, user: Optional[str], text: Any, label: Any = "") -> Dict[str, Any]:
        """Add a pair (its vols) or any Bloomberg ticker to the vol monitor - for the whole desk."""
        out = self._fx(self.fx.add_ticker, self.require_user(user), text, label)
        self.bump()
        return out

    def fx_ticker_remove(self, user: Optional[str], item_id: Any) -> Dict[str, Any]:
        out = self._fx(self.fx.remove_ticker, self.require_user(user), str(item_id or ""))
        self.bump()
        return out

    def fx_set_settings(self, user: Optional[str], source: Any) -> Dict[str, Any]:
        """The Bloomberg pricing source of the vol tickers (BGN by default) - for the whole desk."""
        out = self._fx(self.fx.set_settings, self.require_user(user), source)
        self.bump()
        return out

    def fx_history_sync(self, user: Optional[str], pair: Any = None) -> Dict[str, Any]:
        """Fetch the FX vol history now (the monitor's set; with ``pair`` also that pair's every tenor)."""
        return self._fx(self.fx.sync_history, self.require_user(user), str(pair) if pair else None)

    # ================================================================== spreads over OIS, day by day
    #: z-score windows of a spread: a month, three months and a year of closes
    SPREAD_Z = (20, 60, 250)
    #: closes of a spread's series that are sent for its chart (about a year)
    SPREAD_KEEP = 260

    def spreads(self, user: Optional[str]) -> Dict[str, Any]:
        """The TRY spreads over OIS the desk watches, day by day, and where they stand now.

        * offshore − OIS, tenor by tenor: the history's closes of both curves (FX swap implied up to 9M, cross
          currency from 1Y - the end-of-day matrix's "Offshore"), the days both have a close;
        * VİOP − OIS, contract by contract: the VİOP history (the VİOP sheet's own basis formula, the contracts
          its charts draw and as many days as its "Geçmiş" cell asks for).

        Each: the level now (today's market where there is one - the source in use on the settings page,
        the VİOP sheet's live row - else the last close), its change against 1 / 5 / 21 closes earlier, and
        against the last 20 / 60 / 250 closes its mean, standard deviation, z-score, range and percentile."""
        curves, months, info = self._vol_curves()
        live, viop = self.et.call(self._spread_read, user)
        today = self.history.today().isoformat()
        off_rows: List[Dict[str, Any]] = []
        ois_at = {round(m, 3): label for label, m in months["OIS"].items() if m}
        for label, m in sorted(months["XCCY"].items(), key=lambda kv: kv[1]):
            ois_label = ois_at.get(round(m, 3)) if m else None
            if not ois_label:
                continue
            off, ois = curves["XCCY"].get(label) or {}, curves["OIS"].get(ois_label) or {}
            points = sorted((d, (off[d] - ois[d]) * 100.0) for d in off if d in ois)
            a, b = live["off"].get(label.upper()), live["ois"].get(ois_label.upper())
            now = (a - b) * 100.0 if a is not None and b is not None else None
            row = self._spread_row(points, now, today)
            if row is None:
                continue
            row.update({"id": "off:%g" % m, "tenor": vc.months_label(m) if m >= 1 else ois_label, "months": m,
                        "kind": "XCCY" if m >= 12 else "FX swap ima", "off_label": label, "ois_label": ois_label,
                        "off_now": a, "ois_now": b})
            off_rows.append(row)
        viop_rows: List[Dict[str, Any]] = []
        for c in viop:
            row = self._spread_row(c["points"], c["now"], c["now_day"] or today)
            if row is None:
                continue
            row.update({"id": "viop:%s" % c["ticker"], "tenor": c["name"] or c["ticker"], "ticker": c["ticker"],
                        "expiry": c["expiry"], "to_expiry": c["to_expiry"], "imp_now": c["imp"], "ois_now": c["ois"],
                        "order": c["order"]})
            viop_rows.append(row)
        return {"today": today, "live": self.mode == "live", "windows": list(self.SPREAD_Z), "off": off_rows,
                "viop": viop_rows, "viop_days": live.get("viop_days"), "history": info, "rev": self.history.rev,
                "state": self.history.status(), "gen": self.gen}

    def _spread_row(self, points: List[Tuple[str, float]], now: Optional[float], day: str) -> Optional[Dict[str, Any]]:
        """One spread: ``points`` its closes (day, bp), ``now`` today's level (``None``: none) on ``day``."""
        seen: Dict[str, float] = {}
        for d, v in points:
            if type(v) is float and math.isfinite(v):
                seen[d] = v
        if now is not None and not (type(now) is float and math.isfinite(now)):
            now = None
        past = sorted((d, v) for d, v in seen.items() if now is None or d < day)
        if now is None:
            if not past:
                return None
            level_day, level = past[-1]
            past = past[:-1]
        else:
            level_day, level = day, now
        values = [v for _, v in past]
        out: Dict[str, Any] = {"level": level, "day": level_day, "live": now is not None, "n": len(values) + 1,
                               "first": past[0][0] if past else level_day}
        for name, back in (("d1", 1), ("w1", 5), ("m1", 21)):
            prev = past[-back] if len(past) >= back else None
            out[name] = level - prev[1] if prev else None
            out[name + "_from"] = prev[1] if prev else None
            out[name + "_day"] = prev[0] if prev else None
        bands: Dict[str, Any] = {}
        for n in self.SPREAD_Z:
            part = values[-n:]
            sd = vc.stdev(part) if len(part) >= vc.MIN_Z else None
            mean = sum(part) / len(part) if part else None
            bands[str(n)] = {"n": len(part), "mean": mean if sd else None, "sd": sd,
                             "z": (level - mean) / sd if sd else None,
                             "min": min(part + [level]) if part else None, "max": max(part + [level]) if part else None,
                             "pct": sum(1 for x in part if x < level) / len(part) if sd else None}
        out["bands"] = bands
        keep = past[-(self.SPREAD_KEEP - 1):] + [(level_day, level)]
        out["days"] = [d for d, _ in keep]
        out["values"] = [v for _, v in keep]
        return out

    def _spread_read(self, user: Optional[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Today's quotes the spreads are measured with, and the VİOP history's contracts (engine thread)."""
        book = self._book("tto")
        calc = self._calc(user_key(user) if user else None, book)
        live: Dict[str, Any] = {"ois": {}, "off": {}, "viop_days": None}

        def reader(sheet: str):
            si = book.model.sheet_index[sheet]
            return lambda ref: calc.get(si, *divmod(parse_a1(ref), COLS))

        if ex.SRC_SHEET in book.model.sheet_index:
            get = reader(ex.SRC_SHEET)
            titles = {title: kind for kind, title, _, _, _ in ex.SRC_LISTS}
            for r in range(ex.SRC_FIRST, ex.SRC_FIRST + 60):
                kind = titles.get(get("A%d" % r))
                tenor = get("B%d" % r)
                if kind is None or not isinstance(tenor, str) or not tenor.strip():
                    continue
                if kind == "ois":
                    v = get("I%d" % r)                      # per cent
                    if type(v) is float:
                        live["ois"][tenor.strip().upper()] = v
                else:
                    bid, ask = get("I%d" % r), get("J%d" % r)
                    if type(bid) is float and type(ask) is float:
                        live["off"][tenor.strip().upper()] = (bid + ask) / 2.0
        viop: List[Dict[str, Any]] = []
        if ex.VH_SHEET in book.model.sheet_index:
            get = reader(ex.VH_SHEET)
            days = get("B8")
            live["viop_days"] = days if type(days) is float else None

            def iso(v: Any) -> Optional[str]:
                return serial_to_date(v).isoformat() if type(v) is float and v > 0 else None

            for k in range(ex.VH_SLOTS):
                slot = index_to_col(2 + k)
                ticker, expiry = get("%s4" % slot), get("%s5" % slot)
                if not isinstance(ticker, str) or not ticker.strip() or type(expiry) is not float:
                    continue
                baz = ex.VH_COLS["baz"][k]
                points = []
                for r in range(ex.VH_FIRST, ex.VH_FIRST + ex.VH_ROWS):
                    d, v = iso(get("A%d" % r)), get("%s%d" % (baz, r))
                    if d and type(v) is float:
                        points.append((d, v))
                def now(group: str) -> Optional[float]:          # the sheet's live row: today's last prices
                    v = get("%s%d" % (ex.VH_COLS[group][k], ex.VH_LIVE))
                    return v if type(v) is float else None

                name, order = get("%s6" % slot), get("%s3" % slot)
                viop.append({"ticker": ticker.strip(), "name": name if isinstance(name, str) else "", "expiry": iso(expiry),
                             "order": int(order) if type(order) is float else None, "points": points, "now": now("baz"),
                             "now_day": iso(get("A%d" % ex.VH_LIVE)), "to_expiry": now("days"), "imp": now("imp"), "ois": now("ois360")})
        return live, viop

    def carry_vol(self, user: Optional[str], kind: str = "fly", window: Any = 60, text: str = "") -> Dict[str, Any]:
        """The flies (or spreads) of the Carry & Roll sheet with their realized volatility: carry + roll over
        the sheet's two horizons against the volatility over the same time.  ``kind`` "list": the instruments typed
        (``text``) instead - OIS outrights, spreads and flies of the sheet's tenors, priced by its tenor engine."""
        k = str(kind or "").lower()
        kind = "list" if k.startswith("l") else "spread" if k.startswith("s") else "fly"
        try:
            window = int(window)
        except (TypeError, ValueError):
            window = 60
        if window not in vc.WINDOWS:
            window = 60
        if kind == "list":
            table = self.et.call(self._carry_list, user, str(text or "")[:4000])
        else:
            table = self.et.call(self._carry_table, user, kind)
        curves, months, info = self._vol_curves()
        days = {name: h["days"] for name, h in table["horizons"].items()}
        rows = []
        for r in table["rows"]:
            if r.get("error"):
                rows.append({"label": r["label"], "tenors": r.get("tenors") or [], "kind": r.get("kind") or "", "market": None,
                             "error": r["error"], "n": 0, "closes": 0, "z": {}})
                continue
            item = r.get("item") or vc.item_of(kind, r["tenors"])
            rows.append(vc.carry_row(item, r["market"], {"a": r["a"], "b": r["b"]}, days, curves["OIS"], months["OIS"], window))
        return {"kind": kind, "window": window, "windows": list(vc.WINDOWS), "z_windows": list(vc.Z_WINDOWS),
                "horizons": table["horizons"], "rows": rows, "history": info, "path": table.get("path", ""), "gen": self.gen}

    def _carry_horizons(self, book: Book, calc: Calc) -> Dict[str, Any]:
        """The Carry & Roll sheet's two horizons: label ("1 ay"), business days from the OIS spot date, end date."""
        si = book.model.sheet_index["C & R"]

        def cell(ref: str) -> Any:
            r, c = divmod(parse_a1(ref), COLS)
            return calc.get(si, r, c)

        spot = book.cell("OIS_MAIN!B2")
        spot = calc.get(spot[0], *divmod(spot[1], COLS))
        horizons: Dict[str, Any] = {}
        for name, row in (("a", 3), ("b", 22)):
            text, end = cell("A%d" % row), cell("C%d" % row)
            m = re.search(r":\s*([^–-]+)", text) if isinstance(text, str) else None
            days = vc.week_days(serial_to_date(spot), serial_to_date(end)) if type(spot) is float and type(end) is float else 0
            horizons[name] = {"label": m.group(1).strip() if m else ("Ufuk " + name.upper()), "days": days,
                              "date": serial_to_date(end).isoformat() if type(end) is float else None}
        return horizons

    def _carry_path(self, book: Book, calc: Calc) -> str:
        """What TLREF the carry is compounded with (the carry path chosen, ``extras.CARRY_PATHS``)."""
        if ex.CARRY_SHEET not in book.model.sheet_index:
            return "S1 senaryosu"
        si, rc = book.cell(ex.CARRY_SHEET + "!C2")
        text = calc.get(si, *divmod(rc, COLS))
        return text if isinstance(text, str) else ""

    def _carry_engine(self, book: Book, calc: Calc) -> Dict[float, Dict[str, Optional[float]]]:
        """The tenor engine of the Motor sheet, per tenor (months): its par rate (%) and its carry + roll over
        horizon A and B in bp of its own annuity (receiver), as the Carry & Roll sheet's spread and fly tables take it."""
        si = book.model.sheet_index["Motor"]

        def cell(col: str, row: int) -> Any:
            return calc.get(si, row, parse_a1("%s1" % col) % COLS)

        out: Dict[float, Dict[str, Optional[float]]] = {}
        first_a, last_a = ex.CARRY_ENGINE_A
        first_b = ex.CARRY_ENGINE_B[0]
        for i in range(last_a - first_a + 1):
            months = cell("A", first_a + i)
            if type(months) is not float:
                continue
            row: Dict[str, Optional[float]] = {"par": None, "a": None, "b": None}
            par = cell("B", 306 + i)
            row["par"] = par * 100.0 if type(par) is float else None
            for name, r in (("a", first_a + i), ("b", first_b + i)):
                valid, k, d = cell("H", r), cell("K", r), cell("D", r)
                if valid is True and type(k) is float and type(d) is float and d:
                    row[name] = k / d * 10000.0
            out[months] = row
        return out

    def _carry_list(self, user: Optional[str], text: str) -> Dict[str, Any]:
        """Carry + roll of the instruments typed: an OIS outright (receiver), a spread (flattener: receive the long
        tenor, pay the short one) or a fly (receive the body), from the tenor engine - the tenors of the Carry &
        Roll sheet (1M ... 10Y)."""
        book = self._book("tto")
        if "C & R" not in book.model.sheet_index:
            raise ServiceError("Carry & Roll sayfası bu çalışma kitabında yok")
        calc = self._calc(user_key(user) if user else None, book)
        engine = self._carry_engine(book, calc)
        weights = {"outright": (1.0,), "spread": (-1.0, 1.0), "fly": (-1.0, 2.0, -1.0)}
        grid = ", ".join(vc.months_label(m) for m in sorted(engine))
        rows = []
        for it in vc.parse_items(text)[:40]:
            label = it.get("label") or it.get("raw") or ""
            if not it.get("ok"):
                rows.append({"label": it.get("raw", ""), "error": it.get("error") or "anlaşılamadı"})
                continue
            if it["product"] != "OIS" or it["kind"] not in weights:
                rows.append({"label": label, "tenors": it["tenors"], "kind": it["kind"],
                             "error": "carry yalnız OIS vadesi, spread'i ve fly'ı için"})
                continue
            legs = [engine.get(float(m)) if m is not None else None for m in it["months"]]
            if any(leg is None for leg in legs):
                rows.append({"label": label, "tenors": it["tenors"], "kind": it["kind"], "error": "carry vadeleri: " + grid})
                continue
            w = weights[it["kind"]]
            par = [leg["par"] for leg in legs]
            market = None
            if all(type(p) is float for p in par):
                market = par[0] if it["kind"] == "outright" else sum(x * p for x, p in zip(w, par)) * 100.0
            row = {"label": label, "tenors": it["tenors"], "kind": it["kind"], "item": it, "market": market, "a": None, "b": None}
            for name in ("a", "b"):
                vals = [leg[name] for leg in legs]
                if all(type(v) is float for v in vals):
                    row[name] = sum(x * v for x, v in zip(w, vals))
            rows.append(row)
        return {"rows": rows, "horizons": self._carry_horizons(book, calc), "path": self._carry_path(book, calc)}

    def carry_settings(self, user: Optional[str]) -> Dict[str, Any]:
        """The carry's TLREF path (one's own choice) and its two horizons (months, the OIS sheet's inputs)."""
        book = self._book("tto")
        if ex.CARRY_SHEET not in book.model.sheet_index:
            return {"available": False}
        key = user_key(user) if user else None

        def run():
            calc = self._calc(key, book)

            def get(ref: str) -> Any:
                si, rc = book.cell(ref)
                return calc.get(si, *divmod(rc, COLS))

            names = {n: get("OIS_MAIN!P%d" % (3 + k)) for k, n in enumerate(("S1", "S2", "S3"))}
            options = []
            for name, about in ex.CARRY_PATHS:
                extra = names.get(name)
                options.append({"id": name, "label": name + (" · " + extra if isinstance(extra, str) and extra else ""), "about": about})
            horizons = self._carry_horizons(book, calc) if "C & R" in book.model.sheet_index else {}
            return {"available": True, "path": get(ex.CARRY_SHEET + "!B2"), "about": self._carry_path(book, calc), "options": options,
                    "default": ex.CARRY_DEFAULT, "a": get("OIS_MAIN!B4"), "b": get("OIS_MAIN!D4"), "horizons": horizons}

        return self.et.call(run)

    def set_carry_settings(self, user: Optional[str], path: Any, a: Any, b: Any) -> Dict[str, Any]:
        """Set one's own carry path and horizons (months, 1 … 120)."""
        user = self.require_user(user)
        names = [n for n, _ in ex.CARRY_PATHS]
        path = str(path or "").strip()
        if path not in names:
            raise ServiceError("carry patikası şunlardan biri olmalı: " + ", ".join(names))
        items = [{"ref": ex.CARRY_SHEET + "!B2", "value": path}]
        for ref, value, name in (("OIS_MAIN!B4", a, "Ufuk A"), ("OIS_MAIN!D4", b, "Ufuk B")):
            try:
                months = int(float(str(value).replace(",", ".")))
            except (TypeError, ValueError):
                raise ServiceError("%s ay sayısı olmalı" % name)
            if not 1 <= months <= 120 or float(str(value).replace(",", ".")) != months:
                raise ServiceError("%s 1 ile 120 arasında tam ay olmalı" % name)
            items.append({"ref": ref, "value": months})
        res = self.set_inputs(user, "tto", items)
        if res.get("errors"):
            raise ServiceError("; ".join(res["errors"]))
        return self.carry_settings(user)

    def _carry_table(self, user: Optional[str], kind: str) -> Dict[str, Any]:
        """The rows of the C & R sheet's fly / spread table (label, market, carry + roll over horizon A and B in
        bp) and its two horizons."""
        book = self._book("tto")
        si = book.model.sheet_index.get("C & R")
        if si is None:
            raise ServiceError("Carry & Roll sayfası bu çalışma kitabında yok")
        calc = self._calc(user_key(user) if user else None, book)

        def cell(ref: str) -> Any:
            r, c = divmod(parse_a1(ref), COLS)
            return calc.get(si, r, c)

        def number(v: Any) -> Optional[float]:
            return v if type(v) is float else None

        head = "Kanat / Gövde" if kind == "fly" else "Kısa / Uzun"
        first = next((r for r in range(1, 600) if isinstance(cell("A%d" % r), str) and cell("A%d" % r).strip().startswith(head)), None)
        if first is None:
            raise ServiceError("Carry & Roll sayfasında %s tablosu bulunamadı" % ("fly" if kind == "fly" else "spread"))
        rows = []
        r = first + 1
        while r < first + 400:
            label = cell("A%d" % r)
            if not isinstance(label, str) or "/" not in label:
                break
            rows.append({"label": label.strip(), "tenors": [t.strip() for t in label.split("/")], "market": number(cell("B%d" % r)),
                         "a": number(cell("C%d" % r)), "b": number(cell("D%d" % r))})
            r += 1
        return {"rows": rows, "horizons": self._carry_horizons(book, calc), "path": self._carry_path(book, calc)}

    # ================================================================== broker chat
    def _broker_day(self, date: Optional[str]) -> str:
        day = date or self.today_iso()
        try:
            _dt.date.fromisoformat(day)
        except ValueError:
            raise ServiceError("tarih anlaşılamadı: %s" % day)
        return day

    def _broker_market(self, user: Optional[str]):
        book = self.books.get("tto")
        if book is None:
            return None
        return bl.OisMarket(book, self._calc(user_key(user) if user else None, book))

    @staticmethod
    def _bond_screen(mkt, isin: Optional[str]) -> Optional[Dict[str, Any]]:
        """What the DİBS RV table has of a bond: the clean price in use, the BIST compound yield (%), the modified
        duration - the screen a chat's bond quote is read against."""
        if mkt is None or not isin:
            return None
        try:
            info = bl.bond_info(mkt.book, mkt.calc, isin)
        except Exception:  # noqa: BLE001 - the table may not have the bond
            return None
        if not info or "".join(str(info.get("isin") or "").split()).upper() != isin:
            return None
        y = info.get("yield")
        return {"clean": info.get("clean") if type(info.get("clean")) is float else None,
                "yield": y * 100.0 if type(y) is float and abs(y) < 5 else (y if type(y) is float else None),
                "mod_dur": info.get("mod_dur") if type(info.get("mod_dur")) is float else None,
                "rv": info.get("rv") if type(info.get("rv")) is float else None}      # against the fitted ASW curve, + cheap

    @staticmethod
    def _switch_screen(mkt, q: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A switch on the DİBS RV screen: the longer bond's yield − the shorter one's (bp), and how much cheaper the
        longer bond is than the shorter one against the screen's fitted ASW curve ("Pahalı/ucuz", + cheap; bp)."""
        legs = q.get("legs") or []
        if len(legs) != 2:
            return None
        a, b = (Service._bond_screen(mkt, leg.get("isin")) or {} for leg in legs)
        if q.get("unit") == "px":                          # floaters, CPI linkers: the difference of the clean prices
            if a.get("clean") is None or b.get("clean") is None:
                return None
            return {"screen": b["clean"] - a["clean"], "rv": None,
                    "legs": [{"label": leg.get("label"), "clean": sc["clean"]} for leg, sc in zip(legs, (a, b))]}
        if a.get("yield") is None or b.get("yield") is None:
            return None
        rv = b["rv"] - a["rv"] if a.get("rv") is not None and b.get("rv") is not None else None
        return {"screen": (b["yield"] - a["yield"]) * 100.0, "rv": rv,
                "legs": [{"label": leg.get("label"), "yield": sc["yield"], "rv": sc.get("rv")} for leg, sc in zip(legs, (a, b))]}

    @staticmethod
    def _bond_level(isin: str, unit: Optional[str], value: Any) -> Optional[Dict[str, Any]]:
        """A bond's level as ``bc.near_level`` takes it (``None`` for a bond the catalog does not know)."""
        from . import bonds as bd
        b = bd.by_isin(isin)
        if b is None or type(value) is not float or unit not in ("px", "yld"):
            return None
        mat = _dt.date.fromisoformat(b["maturity"])
        return {"isin": b["isin"], "kind": b.get("kind"), "months": (mat.year - 2000) * 12.0 + mat.month, "unit": unit,
                "value": value, "label": bd.short_label(b)}

    def _bond_nearby(self, user: Optional[str], mkt) -> List[Dict[str, Any]]:
        """The floaters, CPI linkers and bills of the DİBS RV table at their screen price (a bill at its yield)."""
        from . import bonds as bd
        out: List[Dict[str, Any]] = []
        if mkt is None or "tto" not in self.books:
            return out
        try:
            isins = self._list_values(user, *self.BOND_LISTS["dibs"])
        except Exception:  # noqa: BLE001 - a workbook without the table
            return out
        for isin in isins:
            b = bd.by_isin(isin) if isin else None
            if b is None or b.get("kind") not in ("float", "frn", "cpi", "bill", "zero"):
                continue
            sc = self._bond_screen(mkt, isin) or {}
            unit = "yld" if bd.quoted_in_yield(b) else "px"
            lv = self._bond_level(isin, unit, sc.get("yield") if unit == "yld" else sc.get("clean"))
            if lv is not None:
                out.append(lv)
        return out

    def _bond_pick(self, mkt, rows: List[Dict[str, Any]]) -> None:
        """A month that has several bonds of the kind ("jan30": 02.01.30 FRN and 09.01.30 TLREF; "10/02/2027": a bill
        and a bond): the one whose screen level is nearest to the level said - in the unit the line was read in.
        When the screen settles it (one is near, the others far or not of that unit) the line is no longer flagged."""
        from . import bonds as bd
        for q in rows:
            if q.get("product") != "DIBS" or q.get("kind") == "switch" or "bond?" not in (q.get("flags") or []):
                continue
            level = next((q[k] for k in ("price", "bid", "ask") if type(q.get(k)) is float), None)
            same = [i for i in [q.get("isin")] + list(q.get("alts") or [])
                    if i and bd.by_isin(i) is not None and ("yld" if bd.quoted_in_yield(bd.by_isin(i)) else "px") == q.get("unit")]
            if len(same) == 1 and same[0] == q.get("isin"):
                q["flags"].remove("bond?")                   # the others trade on the other unit: "10/02/2027 99.445"
                continue
            if level is None:
                continue
            gaps: Dict[str, float] = {}
            for isin in same:
                sc = self._bond_screen(mkt, isin) or {}
                ref = sc.get("yield") if q.get("unit") == "yld" else sc.get("clean")
                if ref is not None:
                    gaps[isin] = abs(ref - level)
            if not gaps:
                continue
            best = min(gaps, key=lambda i: gaps[i])
            tight = 0.5 if q.get("unit") == "yld" else 1.5

            def far(other: str) -> bool:
                """Another bond of the month that cannot be the one: its screen is far from the level, or - with no
                screen - its coupon is far from the near one's (12.4% next to 36.8%: some twenty points apart)."""
                if other in gaps:
                    return gaps[other] >= 2 * gaps[best] + tight
                a, b = bd.by_isin(best) or {}, bd.by_isin(other) or {}
                return a.get("kind") == b.get("kind") == "fixed" and abs((a.get("coupon") or 0.0) - (b.get("coupon") or 0.0)) >= 5.0

            if gaps[best] <= tight and all(far(i) for i in same if i != best):
                q["flags"].remove("bond?")                   # near one, the others cannot be it: settled
            if best != q.get("isin"):
                b = bd.by_isin(best)
                q["alts"] = [i for i in [q.get("isin")] + list(q.get("alts") or []) if i != best]
                q["isin"], q["key"] = best, "DIBS:" + best
                if b:
                    q["label"] = bd.short_label(b)
                    q["tenors"] = [q["label"]]
                    q["bond_kind"] = b.get("kind")

    @staticmethod
    def _broker_model(mkt, q: Dict[str, Any]) -> Optional[float]:
        """Where the dashboard's own TRY OIS curve has an instrument of the chat (cross-currency: no answer); for a
        bond, its screen price (or yield, for a bill) in the DİBS RV table; for a meeting-dated swap, the bootstrap
        rate of its two days in the 'MPC OIS' table (the trade form's "Piyasa mid")."""
        if mkt is not None and q.get("product") == "DIBS" and q.get("kind") == "switch":
            sw = Service._switch_screen(mkt, q)
            return sw["screen"] if sw else None
        if mkt is not None and q.get("product") == "DIBS":
            sc = Service._bond_screen(mkt, q.get("isin") or str(q.get("key") or "").replace("DIBS:", "")) or {}
            return sc.get("yield") if q.get("unit") == "yld" else sc.get("clean")
        if mkt is None or q.get("product") != "OIS":
            return None
        return bc.model_level(q, lambda t: mkt.par(t) if t in bl.OIS_TENORS else None, mkt.fra_months,
                              lambda a, b: mkt.mpc_span(Service._serial(a), Service._serial(b)))

    @staticmethod
    def _serial(iso: str) -> float:
        return float(date_to_serial(_dt.date.fromisoformat(iso)))

    def _mpc_calendar(self, mkt, day: str) -> Optional[Dict[str, Any]]:
        """The meetings a chat's "dec mpc", "mpc1" are dated with (``bc.mpc_span``): every meeting the dashboard knows -
        the ones held (the calendar's archive) and the workbook's list (OIS_MAIN!P10:P89) - with its effective day: the
        'MPC OIS' table's own for the meetings it covers (the business day after the decision), the day after the
        decision for the others; the OIS spot; ``day``, the day of the lines that do not say theirs."""
        from .history import MEETING_ROWS
        if mkt is None:
            return None
        try:
            table = mkt.mpc_table()
            listed = [mkt.value("OIS_MAIN!P%d" % r) for r in range(MEETING_ROWS[0], MEETING_ROWS[1] + 1)]
        except Exception:  # noqa: BLE001 - a workbook without the table: nothing is dated
            return None
        effective = {serial_to_date(d): serial_to_date(e) for d, e in table["meetings"]}
        days = set(effective) | {serial_to_date(v) for v in listed if type(v) is float}
        for iso in self.history.archive():
            days.add(_dt.date.fromisoformat(iso))
        return {"meetings": [(d, effective.get(d, d + _dt.timedelta(days=1))) for d in sorted(days)],
                "spot": serial_to_date(table["spot"]) if table["spot"] is not None else None, "on": _dt.date.fromisoformat(day)}

    @staticmethod
    def _overnight(rate: float, days: float) -> float:
        """The overnight rate (ACT/365) that compounded every day for ``days`` gives the simple rate ``rate``: what
        TLREF has to average over a meeting's period."""
        return 365.0 * ((1.0 + rate * days / 365.0) ** (1.0 / days) - 1.0)

    def _mpc_implied(self, user: Optional[str], rows: List[Dict[str, Any]], board: Optional[List[Dict[str, Any]]] = None) -> None:
        """A meeting swap of one period - from a meeting to the next - next to the MPC OIS bootstrap: the step at its
        meeting that each of its levels stands for (``implied``, ``kind`` "mpc", bp) - the level's overnight
        equivalent − that of the bootstrap's rate for the period before the meeting (from the meeting before it, or
        from the OIS spot for the first one).  ``model``: the bootstrap's own step for the meeting."""
        items = [(q, ("bid", "ask", "price")) for q in rows] + [(r, ("bid", "ask", "last", "best_bid", "best_ask")) for r in board or ()]
        items = [(q, f) for q, f in items if q.get("kind") == "mpc" and (q.get("mpc") or {}).get("start") and (q.get("mpc") or {}).get("meeting")]
        mkt = self._broker_market(user) if items else None
        if mkt is None:
            return
        try:
            days = sorted(mkt.mpc_table()["lndf"])
        except Exception:  # noqa: BLE001 - a workbook without the table
            return
        for q, fields in items:
            s, e = self._serial(q["mpc"]["start"]), self._serial(q["mpc"]["end"])
            if s not in days or e not in days or days.index(s) == 0 or days.index(e) != days.index(s) + 1:
                continue                                    # several periods, or days the table does not have
            p = days[days.index(s) - 1]
            prev, model = mkt.mpc_span(p, s), mkt.mpc_span(s, e)
            if prev is None:
                continue
            base = self._overnight(prev, s - p)
            out: Dict[str, Any] = {"kind": "mpc", "meeting": q["mpc"]["meeting"], "days": e - s, "prev": prev * 100.0,
                                   "prev_on": base * 100.0, "prev_from": serial_to_date(p).isoformat(), "prev_to": q["mpc"]["start"],
                                   "model": None if model is None else (self._overnight(model, e - s) - base) * 1e4,
                                   "model_level": None if model is None else model * 100.0}
            for f in fields:
                if type(q.get(f)) is float:
                    out[f] = (self._overnight(q[f] / 100.0, e - s) - base) * 1e4
            q["implied"] = out

    def _fx_market(self, user: Optional[str]) -> Optional[Callable[[str, float, str], Optional[Dict[str, float]]]]:
        """What a USDTRY swap quote in points means as a TRY rate - with the Forward sheet's own numbers: the spot
        (F2), the days of each tenor from its offshore table (G6:G17, Bloomberg's DAYS_TO_MTY) and the USD rate of
        as many days from its USD table (U6:Y26), the bid side with the USD ask and the ask side with the USD bid
        as the sheet prices a forward.  TRY % = ((1 + points / 10 000 / spot) · (1 + USD · d / 360) − 1) · 360 / d."""
        book = self.books.get("tto")
        if book is None or "Forward" not in book.model.sheet_index:
            return None
        calc = self._calc(user_key(user) if user else None, book)
        si = book.model.sheet_index["Forward"]

        def v(addr: str) -> Any:
            return calc.get(si, *divmod(parse_a1(addr), COLS))

        spot = v("F2")
        if type(spot) is not float or spot <= 0:
            return None
        days: Dict[str, float] = {}
        for r in range(6, 18):
            label, d = v("H%d" % r), v("G%d" % r)
            if isinstance(label, str) and type(d) is float and d > 0:
                days[label.strip().upper().replace("12M", "1Y")] = d
        usd = []
        for r in range(6, 27):
            d, b, m, a = v("U%d" % r), v("W%d" % r), v("X%d" % r), v("Y%d" % r)
            if type(d) is float and type(m) is float:
                usd.append((d, b if type(b) is float else m, m, a if type(a) is float else m))
        usd.sort()
        if not usd:
            return None
        spot_day = v("I2")
        if isinstance(spot_day, str):
            try:
                spot_day = parse_date(spot_day)
            except Exception:  # noqa: BLE001
                spot_day = None

        def tenor_days(label: str) -> Optional[float]:
            label = label.upper()
            if label in days:
                return days[label]
            if label in ("O/N", "T/N", "S/N"):
                if label == "S/N" and type(spot_day) is float:
                    wd = serial_to_date(spot_day).weekday()
                    return 3.0 if wd == 4 else 1.0             # Friday's spot: to Monday
                return 1.0
            m = re.match(r"^(\d+)([WMY])$", label)
            if not m:
                return None
            n = int(m.group(1))
            return {"W": 7.0 * n, "M": 30.4375 * n, "Y": 365.0 * n}[m.group(2)]

        def rate_usd(d: float, col: int) -> float:
            if d <= usd[0][0]:
                return usd[0][col]
            for (d1, *r1), (d2, *r2) in zip(usd, usd[1:]):
                if d1 <= d <= d2:
                    return r1[col - 1] + (d - d1) * (r2[col - 1] - r1[col - 1]) / (d2 - d1)
            return usd[-1][col]

        def implied(label: str, points: float, side: str) -> Optional[Dict[str, float]]:
            d = tenor_days(label)
            if not d or d <= 0:
                return None
            col = {"bid": 3, "ask": 1}.get(side, 2)             # the bid side with the USD ask, the ask side with the USD bid
            u = rate_usd(d, col)
            r = ((1.0 + points / 10000.0 / spot) * (1.0 + u / 100.0 * d / 360.0) - 1.0) * 360.0 / d * 100.0
            return {"rate": r, "days": d, "usd": u, "spot": spot}

        return implied

    def _bond_implied(self, user: Optional[str], rows: List[Dict[str, Any]], board: Optional[List[Dict[str, Any]]] = None) -> None:
        """The yield a bond's price quote stands for, from the DİBS RV screen: yield − (price − screen price) /
        (screen price · modified duration) (``implied``, in per cent; ``kind`` "bond")."""
        items = [(q, ("bid", "ask", "price")) for q in rows] + [(r, ("bid", "ask", "last", "level", "best_bid", "best_ask")) for r in board or ()]
        if not any(q.get("product") == "DIBS" and q.get("unit") == "px" for q, _ in items):
            return
        book = self.books.get("tto")
        if book is None:
            return
        mkt = bl.OisMarket(book, self._calc(user_key(user) if user else None, book))
        for q, fields in items:
            if q.get("product") != "DIBS" or q.get("unit") != "px":
                continue
            sc = self._bond_screen(mkt, q.get("isin") or str(q.get("key") or "").replace("DIBS:", ""))
            if not sc or sc.get("clean") is None or sc.get("yield") is None or not sc.get("mod_dur"):
                continue
            out: Dict[str, Any] = {"kind": "bond", "screen": sc["clean"], "screen_yield": sc["yield"], "mod_dur": sc["mod_dur"]}
            for f in fields:
                if type(q.get(f)) is float:
                    out[f] = sc["yield"] - (q[f] - sc["clean"]) / (sc["clean"] * sc["mod_dur"]) * 100.0
            q["implied"] = out if any(f in out for f in fields) else None

    @staticmethod
    def _switch_legs(mkt, rows: List[Dict[str, Any]]) -> None:
        """A switch written leg by leg ("jan30 700 vs jul30 750 switch trading"): its level from the legs' - the
        longer leg's yield − the shorter one's (bp), a price made a yield on the DİBS RV screen as a bond's quote is
        (yield − (price − screen price) / (screen price · modified duration)); floaters and CPI linkers: the
        difference of the two prices."""
        for q in rows:
            if not q.get("by_legs") or q.get("kind") != "switch" or q.get("event") == "ref":
                continue
            legs = q.get("legs") or []
            if len(legs) != 2 or any(type(leg.get("level")) is not float for leg in legs):
                continue
            if q.get("unit") == "px":
                if all(leg.get("unit") == "px" for leg in legs):
                    q["price"] = legs[1]["level"] - legs[0]["level"]
                continue
            ys = []
            for leg in legs:
                if leg.get("unit") == "yld":
                    ys.append(leg["level"])
                    continue
                sc = Service._bond_screen(mkt, leg.get("isin")) or {}
                if sc.get("clean") is None or sc.get("yield") is None or not sc.get("mod_dur"):
                    break
                leg["yield"] = sc["yield"] - (leg["level"] - sc["clean"]) / (sc["clean"] * sc["mod_dur"]) * 100.0
                ys.append(leg["yield"])
            if len(ys) == 2:
                q["price"] = (ys[1] - ys[0]) * 100.0

    def _switch_implied(self, user: Optional[str], rows: List[Dict[str, Any]], board: Optional[List[Dict[str, Any]]] = None) -> None:
        """A switch next to the DİBS RV screen (``implied``, ``kind`` "switch"): the screen's switch, and where the
        level said stands - ``vs_screen`` (level − the screen's switch) and ``vs_curve`` (the longer bond's
        cheapness against the shorter one on the fitted ASW curve, at the level said: the screen's own plus the
        level's distance from the screen's switch).  Positive: the longer bond is cheap (buy it, sell the shorter).
        The level: the trade's, else the middle of bid and ask, else the one side said."""
        items = [(q, ("price", "bid", "ask")) for q in rows] + [(r, ("last", "bid", "ask", "level")) for r in board or ()]
        items = [(q, f) for q, f in items if q.get("product") == "DIBS" and q.get("kind") == "switch" and q.get("legs")]
        book = self.books.get("tto")
        if not items or book is None:
            return
        mkt = bl.OisMarket(book, self._calc(user_key(user) if user else None, book))
        for q, fields in items:
            sw = self._switch_screen(mkt, q)
            if sw is None:
                continue
            got = {f: q[f] for f in fields if type(q.get(f)) is float}
            first = fields[0]
            if first in got:
                at = got[first]
            elif "bid" in got and "ask" in got:
                at = (got["bid"] + got["ask"]) / 2.0
            else:
                at = next(iter(got.values()), None)
            out = dict(sw, kind="switch", at=at)
            out["vs_screen"] = at - sw["screen"] if at is not None else None
            out["vs_curve"] = sw["rv"] + out["vs_screen"] if at is not None and sw["rv"] is not None else None
            q["implied"] = out

    def _fx_implied(self, user: Optional[str], rows: List[Dict[str, Any]], board: Optional[List[Dict[str, Any]]] = None) -> None:
        """The TRY rate each FX swap quote in points stands for (``implied``: bid / ask / price / last, in per cent)."""
        self._bond_implied(user, rows, board)
        self._switch_implied(user, rows, board)
        self._mpc_implied(user, rows, board)
        if not any(q.get("product") == "FX" for q in rows) and not any(r.get("product") == "FX" for r in board or ()):
            return
        fn = self._fx_market(user)
        if fn is None:
            return
        for q, fields in [(q, ("bid", "ask", "price")) for q in rows] + [(r, ("bid", "ask", "last")) for r in board or ()]:
            if q.get("product") != "FX" or not q.get("tenors"):
                continue
            out: Dict[str, Any] = {}
            for f in fields:
                if type(q.get(f)) is float:
                    side = f if f in ("bid", "ask") else (q.get("side") if f == "price" else q.get("last_side")) or "mid"
                    hit = fn(q["tenors"][0], q[f], side)
                    if hit:
                        out[f] = hit["rate"]
                        out["days"], out["usd"], out["spot"] = hit["days"], hit["usd"], hit["spot"]
            q["implied"] = out or None

    def _broker_close(self, q: Dict[str, Any]) -> Optional[float]:
        """The last close the history keeps of an outright the curve cannot place (a cross-currency swap has no
        curve in the workbook): enough to find the big figure of a shortened level."""
        if q.get("kind") != "outright" or q.get("unit") != "pct":
            return None
        try:
            curves = self._vol_curves()[0]
        except Exception:  # noqa: BLE001 - no history is no reason to lose the chat
            return None
        series = (curves.get(q.get("product")) or {}).get(q["tenors"][0])
        return series[max(series)] if series else None

    def _broker_rows(self, user: Optional[str], text: str, date: Optional[str]) -> List[Dict[str, Any]]:
        """A pasted chat as rows to keep.  A level without its big figure ("90 bid", "90/10") is completed from
        what the chat last said about the instrument - in the same paste, then earlier that day - then from the
        curve, and for what the curve does not have (cross-currency) from its last close in the history."""
        import hashlib
        day = self._broker_day(date)
        mkt = self._broker_market(user)
        kept: Dict[str, List[Dict[str, Any]]] = {}

        def before(q: Dict[str, Any]) -> List[Dict[str, Any]]:
            """What is kept of the message's day up to its time (all of the day for a message without a time)."""
            date = q.get("date") or day
            if date not in kept:
                kept[date] = self.store.broker_quotes(date)
            return [r for r in kept[date] if not q.get("time") or r["time"] <= q["time"]]

        def ref(q: Dict[str, Any]) -> Optional[float]:
            for r in reversed(before(q)):
                if r.get("ok") and r.get("key") == q["key"] and r.get("unit") == q.get("unit"):
                    for name in ("price", "ask", "bid"):
                        if r.get(name) is not None:
                            return r[name]
            model = self._broker_model(mkt, q)
            return model if model is not None else self._broker_close(q)

        def standing(q: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            return next((row for row in bc.board(before(q)) if row["key"] == q["key"]), None)

        screen: List[List[Dict[str, Any]]] = []

        def nearby(q: Dict[str, Any]) -> List[Dict[str, Any]]:
            """The bonds priced before the line - in the day's chat, then on the DİBS RV screen."""
            if not screen:
                screen.append(self._bond_nearby(user, mkt))
            said: Dict[str, Dict[str, Any]] = {}
            for r in before(q):
                if r.get("ok") and r.get("product") == "DIBS" and r.get("isin"):
                    v = next((r[k] for k in ("price", "ask", "bid") if type(r.get(k)) is float), None)
                    lv = self._bond_level(r["isin"], r.get("unit"), v)
                    if lv is not None:
                        said[r["isin"]] = lv                  # the last word on a bond stands
            return list(said.values()) + screen[0]

        rows = bc.parse_chat(str(text or "")[:200000], ref, _dt.date.today(), standing, nearby, self._mpc_calendar(mkt, day))
        self._bond_pick(mkt, rows)
        self._switch_legs(mkt, rows)
        now = _dt.datetime.now().strftime("%H:%M:%S")
        seen: Dict[Tuple, int] = {}
        for q in rows:
            q["date"] = q.get("date") or day                 # a date line of the chat itself wins
            q["timed"] = bool(q.get("time"))
            q["time"] = q.get("time") or now                  # typed without a time: the moment it was entered
            if q.get("ok"):
                q["model"] = self._broker_model(mkt, q)       # where the curve had it when it was entered
            # what makes a row "the same row" when a stretch of chat is pasted again: when it was said, by whom
            # and the words - not how they were read (a shortened level is completed from what stands before it)
            said_as = (q["date"], q["time"], q.get("sender") or "", q.get("raw") or "")
            nth = seen[said_as] = seen.get(said_as, -1) + 1   # the second quote of an "oco" message, a repeated line
            q["mark"] = hashlib.sha1("\x1f".join(said_as[2:] + (str(nth),)).encode("utf-8")).hexdigest()[:20]
        return rows

    # ------------------------------------------------------------------ who is who in the chats
    def _people(self) -> Dict[str, Dict[str, Any]]:
        """The desk's list of the names that write in the chats: name -> {"name", "source", "party"}.
        "party" is "biz" (our own desk) or "broker"; "source" the house ("Tullett", "ICAP" ... or our desk)."""
        saved = self.store.get("broker.people", {})
        return saved if isinstance(saved, dict) else {}

    def _who(self, people: Dict[str, Dict[str, Any]], q: Dict[str, Any], source: str = "", party: str = "") -> Tuple[str, str]:
        """(source, party) of a line: from the list for a known sender, else what was chosen for the paste."""
        person = bc.person_of(people, q.get("sender"))
        if person is not None:
            return person.get("source") or source, person.get("party") or party
        return source, party

    def _broker_changed(self) -> None:
        """Broker Chat changed: its count (the live stream's ``broker``: a box of the board asks again) and a new generation
        (its page reads again)."""
        with self._gen_lock:
            self.broker_changes += 1
        self.bump()

    def broker_people(self, user: Optional[str] = None) -> Dict[str, Any]:
        """Every name of the list and every sender the kept chats have, with how many lines each wrote."""
        people = self._people()
        seen = self.store.broker_senders()
        out: Dict[str, Dict[str, Any]] = {}
        for key, p in people.items():
            out[key] = {"name": p.get("name") or key, "source": p.get("source") or "", "party": p.get("party") or "", "known": True,
                        "lines": 0, "last": None}
        for name, n, last in seen:
            key = bc.person_key(name)
            hit = bc.person_of(people, name)
            row = out.get(key)
            if row is None and hit is not None:
                row = out.get(bc.person_key(hit.get("name")))
            if row is None:
                row = out[key] = {"name": name, "source": "", "party": "", "known": False, "lines": 0, "last": None}
            elif row["name"].upper() == row["name"] or row["name"].lower() == row["name"]:
                row["name"] = name                          # the spelling of the chat, rather than one typed by hand
            row["lines"] += n
            row["last"] = max(filter(None, (row["last"], last)), default=None)
        sources = sorted({p["source"] for p in out.values() if p["source"]} | set(self.store.broker_sources()))
        return {"people": sorted(out.values(), key=lambda p: (p["party"] != "", p["name"])), "sources": sources}

    def broker_set_people(self, user: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Change the list: ``[{"name", "source", "party"}]``.  A name with neither a source nor a party
        is taken off it.  Kept for everyone; the chats already kept are shown by the new list at once."""
        self.require_user(user)
        if not isinstance(items, list):
            raise ServiceError("liste bekleniyor")
        people = dict(self._people())
        for it in items[:500]:
            if not isinstance(it, dict):
                continue
            name = " ".join(str(it.get("name") or "").split())[:60]
            key = bc.person_key(name)
            if not key:
                continue
            party = str(it.get("party") or "").lower()
            if party not in bc.PARTIES:
                party = ""
            source = " ".join(str(it.get("source") or "").split())[:40]
            if not source and not party:
                people.pop(key, None)
            else:
                people[key] = {"name": name, "source": source, "party": party}
        self.store.put("broker.people", people)
        self._broker_changed()
        return self.broker_people(user)

    # ------------------------------------------------------------------ a chat: read, keep, show
    def broker_parse(self, user: Optional[str], text: str, date: Optional[str] = None, source: str = "",
                     party: str = "") -> Dict[str, Any]:
        """How a pasted chat would be read - nothing is kept.  ``dup`` marks what is stored already; every line
        says whose it is (from the list of names, or the source and party chosen for the paste)."""
        return self.et.call(self._broker_parse, user, text, date, source, party)

    def _broker_parse(self, user, text, date, source="", party="") -> Dict[str, Any]:
        rows = self._broker_rows(user, text, date)
        have: Dict[str, set] = {}
        people = self._people()
        source, party = self._paste_owner(source, party)
        senders: Dict[str, Dict[str, Any]] = {}
        for q in rows:
            if q["date"] not in have:
                have[q["date"]] = self.store.broker_marks(q["date"])
            q["dup"] = (q["time"], q["mark"]) in have[q["date"]]
            q["source"], q["party"] = self._who(people, q, source, party)
            if q.get("sender"):
                p = bc.person_of(people, q["sender"])
                s = senders.setdefault(bc.person_key(q["sender"]), {"name": q["sender"], "known": p is not None, "lines": 0,
                                                                    "source": (p or {}).get("source") or "",
                                                                    "party": (p or {}).get("party") or ""})
                s["lines"] += 1
        self._fx_implied(user, rows)
        return {"date": self._broker_day(date), "rows": rows, "quotes": sum(1 for q in rows if q.get("ok")),
                "texts": sum(1 for q in rows if not q.get("ok")), "known": sum(1 for q in rows if q["dup"]),
                "senders": list(senders.values())}

    @staticmethod
    def _paste_owner(source: Any, party: Any) -> Tuple[str, str]:
        source = " ".join(str(source or "").split())[:40]
        party = str(party or "").lower()
        return source, party if party in bc.PARTIES else ""

    def broker_add(self, user: str, text: str, date: Optional[str] = None, source: str = "", texts: bool = True,
                   party: str = "") -> Dict[str, Any]:
        """Keep a pasted chat: every line with its time, sender, reading - and whose it is: the list of names
        says it for a known sender, ``source`` / ``party`` for the others.  Pasting a stretch again adds only
        what is new.  ``texts`` off: lines that name no instrument are left out."""
        user = self.require_user(user)
        res = self.et.call(self._broker_add, user, text, date, source, texts, party)
        self._broker_changed()
        return res

    def _broker_add(self, user, text, date, source, texts, party="") -> Dict[str, Any]:
        rows = self._broker_rows(user, text, date)
        if not texts:
            rows = [q for q in rows if q.get("ok")]
        if not rows:
            raise ServiceError("kaydedilecek satır yok")
        source, party = self._paste_owner(source, party)
        people = self._people()
        for q in rows:
            q["source"], q["party"] = self._who(people, q, source, party)
        ids, skipped = self.store.add_broker_quotes(rows, user)
        return {"saved": len(ids), "skipped": skipped, "quotes": sum(1 for q in rows if q.get("ok")), "ids": ids,
                "dates": sorted({q["date"] for q in rows})}

    def broker(self, user: Optional[str], date: Optional[str] = None, date_to: Optional[str] = None,
               part: Optional[str] = None) -> Dict[str, Any]:
        """The chat of a day (or of every day between two dates) in the order it was said, and where every
        instrument stands after it, next to the dashboard's own curve.  ``part="board"``: the board alone (a box of it
        on a launchpad, in the side drawer, in a window of its own) - not the lines, the days or the trades not entered."""
        if part not in (None, "", "board"):
            raise ServiceError("bilinmeyen kısım: %s" % str(part)[:40])
        return self.et.call(self._broker, user, date, date_to, part == "board")

    def _broker(self, user, date, date_to, board_only: bool = False) -> Dict[str, Any]:
        today = self.today_iso()
        day = self._broker_day(date)
        last = self._broker_day(date_to) if date_to else day
        if last < day:
            day, last = last, day
        changes = self.broker_changes                    # (before the board is made: a change while it is made counts after)
        rows, table, resets = self._broker_board(user, day, last)
        if board_only:
            self._fx_implied(user, [], table)
            return {"date": day, "to": last, "ranged": day != last, "today": today, "is_today": day == today == last, "board": table,
                    "gen": self.gen, "changes": changes, "stale_minutes": self._broker_stale_minutes(), "live": last >= today,
                    "now": now_iso()}
        self._fx_implied(user, rows, table)
        return {"date": day, "to": last, "ranged": day != last, "today": today, "is_today": day == today == last,
                "rows": rows, "board": table, "dates": self.store.broker_dates(), "resets": resets, "gen": self.gen,
                # the desk's trades of the chat not in Günlük İşlemler, of the day shown (what "Chat ↔ blotter" lists)
                "unbooked": self._broker_recon(day, last)["missing"],
                # the best prices are the fresh ones: older than this a broker's quote is stale - on a board that ends today
                "stale_minutes": self._broker_stale_minutes(), "live": last >= today, "now": now_iso()}

    #: minutes after which a broker's quote is stale - greyed with its age, never the best price - unless the desk set it
    BROKER_STALE_MINUTES = 10

    def _broker_stale_minutes(self) -> int:
        v = self.store.get("broker.settings", {})
        m = v.get("stale_minutes") if isinstance(v, dict) else None
        return m if type(m) is int and 1 <= m <= 1440 else self.BROKER_STALE_MINUTES

    def broker_settings(self, user: str, stale_minutes: Any) -> Dict[str, Any]:
        """The board's stale limit, for the whole desk: after how many minutes (1 - 1440) a broker's quote no longer
        counts as the best price."""
        user = self.require_user(user)
        try:
            m = int(str(stale_minutes).strip())
        except (TypeError, ValueError):
            raise ServiceError("bayat sınırı dakika olarak yazılır: %r" % stale_minutes)
        if not 1 <= m <= 1440:
            raise ServiceError("bayat sınırı 1 ile 1440 dakika arasında olmalı")
        self.store.put("broker.settings", {"stale_minutes": m, "by": user, "at": now_iso()})
        self._broker_changed()
        return {"stale_minutes": m}

    @staticmethod
    def _broker_house(q: Dict[str, Any]) -> str:
        """Whose quote a line is on the board: its house (the source) - its sender when no source is known."""
        return q.get("source") or q.get("sender") or ""

    def _broker_board(self, user, day: str, last: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """The kept lines of the days, each with whose it is, and the board they make (resets applied), each
        instrument next to where the dashboard has it.  A board that ends today is read with the clock: its best
        prices are the brokers' fresh quotes (``bc.board``); one of a day gone by stands as it was at the end."""
        rows = self.store.broker_quotes(day, last)
        # the list of names as it is now: a name assigned after its lines were kept shows them as its own
        people = self._people()
        for q in rows:
            q["source"], q["party"] = self._who(people, q, q.get("source") or "", q.get("party") or "")
        mkt = self._broker_market(user)
        # a reset of the board: what was said up to then no longer stands on it (the lines stay in the log)
        resets = [r for r in self._broker_resets() if day <= str(r.get("at", ""))[:10] <= last]

        def cleared(q: Dict[str, Any]) -> bool:
            # on the board when it was reset (kept before it, whatever time the chat gave it - a broker's clock
            # ahead of ours, a time typed ahead), or said before the reset (a chat pasted after it); a line kept
            # after the reset and said after it - in its very second too - stands
            stamp = "%s %s" % (q.get("date") or "", q.get("time") or "")
            return any((r.get("key") in ("*", q.get("key")))
                       and (stamp < r.get("at", "") or (type(r.get("upto")) is int and int(q.get("id") or 0) <= r["upto"]))
                       for r in resets)

        live = last >= self.today_iso()
        table = bc.board([q for q in rows if not cleared(q)] if resets else rows, lambda q: q.get("party") == "biz",
                         _dt.datetime.now() if live else None, self._broker_stale_minutes() * 60.0 if live else None, self._broker_house)
        for row in table:
            row.update(bc.against(row, self._broker_model(mkt, row)))
        return rows, table, resets

    def _broker_resets(self) -> List[Dict[str, Any]]:
        v = self.store.get("broker.resets", [])
        return [r for r in v if isinstance(r, dict) and r.get("at")] if isinstance(v, list) else []

    def broker_reset(self, user: str, date: Optional[str] = None, key: Optional[str] = None, undo: bool = False) -> Dict[str, Any]:
        """Clear the board - every instrument, or one (``key``) - from now on: what was said until now no longer
        stands on it, the log keeps every line.  On a day other than today the whole day is cleared.  ``undo``
        takes the last reset of the day back."""
        user = self.require_user(user)
        day = self._broker_day(date)
        resets = self._broker_resets()
        if undo:
            idx = max((i for i, r in enumerate(resets) if str(r.get("at", ""))[:10] == day), default=None)
            if idx is None:
                raise ServiceError("bu günde sıfırlama yok")
            resets.pop(idx)
        else:
            at = "%s %s" % (day, _dt.datetime.now().strftime("%H:%M:%S") if day == self.today_iso() else "23:59:59")
            kept = self.store.broker_quotes(day, day)
            resets.append({"at": at, "key": str(key or "*")[:80], "label": "", "by": user,
                           "upto": max([int(q.get("id") or 0) for q in kept] or [0])})
            if key:
                resets[-1]["label"] = next((r.get("label") or "" for r in self.store.broker_quotes(day, day) if r.get("key") == key), "")
            resets = resets[-500:]
        self.store.put("broker.resets", resets)
        self._broker_changed()
        return self.broker(user, day)

    # ------------------------------------------------------------------ the chat against the blotter
    def broker_recon(self, user: Optional[str], date: Optional[str] = None, date_to: Optional[str] = None) -> Dict[str, Any]:
        """The desk's own trades said in the chat (trade lines whose party is "biz") next to Günlük İşlemler: entered
        or not (``bc.reconcile``: the same instrument at the same level within a quarter of an hour, or entered from
        the line itself), with what was decided by hand.  ``missing``: how many are not entered."""
        day = self._broker_day(date)
        last = self._broker_day(date_to) if date_to else day
        if last < day:
            day, last = last, day
        return self._broker_recon(day, last)

    def _broker_recon(self, day: str, last: str) -> Dict[str, Any]:
        people = self._people()
        chats = []
        for q in self.store.broker_trades(day, last):
            if not q.get("ok"):
                continue
            q["source"], q["party"] = self._who(people, q, q.get("source") or "", q.get("party") or "")
            if q["party"] == "biz":
                chats.append(q)
        entries = bl.trade_entries(self.store.trades(day, last))
        overrides = self._recon_overrides()
        states = bc.reconcile(chats, entries, overrides)
        by_id = {e["id"]: e for e in entries}
        matched = {s["entry"] for s in states.values() if s.get("entry") is not None}

        def entry(e: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if e is None:
                return None
            return {"id": e["id"], "ids": e["ids"], "kind": e["kind"], "label": e["label"], "date": e["date"],
                    "time": str(e.get("at") or "")[11:16], "by": e.get("by"), "taken": e["id"] in matched}

        items = []
        for q in chats:
            st = states.get(q["id"]) or {"state": "missing"}
            o = overrides.get(str(q["id"])) or {}
            items.append({"id": q["id"], "date": q["date"], "time": q["time"], "sender": q.get("sender") or "", "source": q.get("source") or "",
                          "raw": q.get("raw") or "", "state": st["state"], "gap": st.get("gap"), "entry": entry(by_id.get(st.get("entry"))),
                          "by": o.get("by") if st["state"] in ("manual", "ignored") else None, "q": q})
        return {"date": day, "to": last, "ranged": day != last, "today": self.today_iso(), "items": items,
                "missing": sum(1 for x in items if x["state"] == "missing"), "entries": [entry(e) for e in entries],
                "window": bc.MATCH_WINDOW}

    def _recon_overrides(self) -> Dict[str, Dict[str, Any]]:
        v = self.store.get("broker.recon", {})
        return v if isinstance(v, dict) else {}

    def broker_recon_set(self, user: str, quote_id: Any, action: str, trade_id: Any = None) -> Dict[str, Any]:
        """What the desk decides about one trade line of the chat, for everyone: ``match`` it with a trade of
        Günlük İşlemler of its day (``trade_id``), ``ignore`` it (it will not be entered), ``reject`` the trade it was
        matched with (not this one) or ``undo`` what was decided."""
        user = self.require_user(user)
        if action not in ("match", "ignore", "reject", "undo"):
            raise ServiceError("bilinmeyen işlem: %r" % action)
        try:
            qid = int(quote_id)
        except (TypeError, ValueError):
            raise ServiceError("chat satırı bekleniyor")
        q = self.store.broker_quote(qid)
        if q is None or q.get("event") != "trade":
            raise ServiceError("chat'te böyle bir işlem satırı yok", 404)
        overrides = dict(self._recon_overrides())
        key = str(qid)
        if action == "undo":
            overrides.pop(key, None)
        elif action == "ignore":
            overrides[key] = {"ignore": True, "by": user, "at": now_iso()}
        else:
            try:
                t = self.store.trade(int(trade_id))
            except (TypeError, ValueError):
                t = None
            if t is None:
                raise ServiceError("Günlük İşlemler'de böyle bir işlem yok", 404)
            if action == "match":
                if t["trade_date"] != q["date"]:
                    raise ServiceError("işlem başka bir günün (%s): chat satırı %s" % (t["trade_date"], q["date"]))
                overrides[key] = {"match": t["id"], "by": user, "at": now_iso()}
            else:
                old = (overrides.get(key) or {}).get("reject") or []
                overrides[key] = {"reject": sorted(set(old) | {t["id"]}), "by": user, "at": now_iso()}
        if len(overrides) > 5000:                          # the oldest decisions go first
            overrides = dict(sorted(overrides.items(), key=lambda kv: str(kv[1].get("at") or ""))[-5000:])
        self.store.put("broker.recon", overrides)
        self.bump()
        return self._broker_recon(q["date"], q["date"])

    def chat_unbooked(self) -> Optional[int]:
        """How many of today's trades of the desk in the chat are not in Günlük İşlemler (the badge of the menu)."""
        try:
            return self._broker_recon(self.today_iso(), self.today_iso())["missing"]
        except Exception:  # noqa: BLE001 - a status is never lost to it
            return None

    def broker_delete_many(self, user: str, ids: List[Any]) -> Dict[str, Any]:
        """Delete the lines ticked in the log (for everyone)."""
        self.require_user(user)
        n = 0
        for i in list(ids or [])[:5000]:
            try:
                n += 1 if self.store.delete_broker_quote(int(i)) else 0
            except (TypeError, ValueError):
                continue
        if n:
            self._broker_changed()
        return {"deleted": n}

    def broker_delete(self, user: str, quote_id: int) -> Dict[str, Any]:
        self.require_user(user)
        if not self.store.delete_broker_quote(int(quote_id)):
            raise ServiceError("kayıt bulunamadı", 404)
        self._broker_changed()
        return {"deleted": int(quote_id)}

    def broker_export(self, user: Optional[str], date: Optional[str] = None, date_to: Optional[str] = None) -> Tuple[bytes, str]:
        """The chat of a day or a period as an .xlsx file: the board (the brokers' best bid and offer, whose and how
        old), every broker's quotes, then every line."""
        return self.et.call(self._broker_export, user, date, date_to)

    def _broker_export(self, user, date, date_to) -> Tuple[bytes, str]:
        from .xlsx import XlsxBook
        data = self._broker(user, date, date_to)
        names = {u["name"]: u["display"] for u in self.store.users()}
        kinds = {"outright": "Outright", "spread": "Spread", "fly": "Fly", "fra": "FRA", "fwd": "Forward", "mpc": "MPC"}
        events = {"quote": "Kota", "trade": "İşlem", "ref": "Geri çekildi", "interest": "İlgi", "level": "Seviye", "note": "Not",
                  "text": "Metin"}

        def minutes(s: Any) -> Optional[float]:
            return round(s / 60.0, 1) if type(s) is float else None

        wb = XlsxBook()
        ws = wb.add_sheet("Tahta")
        ws.row(1, 1, ["Ürün", "Tür", "Enstrüman", "Birim", "Bid", "Bid saati", "Ask", "Ask saati", "Son işlem", "İşlem saati",
                      "Model mid", "Bid − mid (bp)", "Ask − mid (bp)", "Bizim bid", "Bizim ask", "İşlemi yapan", "Bid kimde", "Ask kimde",
                      "Bid yaşı (dk)", "Ask yaşı (dk)"], bold=True, fill="E7E6E6")
        for i, r in enumerate(data["board"]):
            fmt = "#,##0.00" if r["unit"] == "pct" else "#,##0.0"
            # the best bid and offer of the brokers (the fresh ones, on a board of today), with whose they are and their age
            line = [r["product"], kinds.get(r["kind"], r["kind"]), r["label"], "%" if r["unit"] == "pct" else "bp", r.get("best_bid"),
                    r.get("best_bid_time"), r.get("best_ask"), r.get("best_ask_time"), r["last"], r["last_time"], r["mid"],
                    r.get("best_bid_diff"), r.get("best_ask_diff"), r.get("our_bid"), r.get("our_ask"),
                    {"biz": "Biz", "broker": "Broker"}.get(r.get("last_by") or "", ""), r.get("best_bid_by"), r.get("best_ask_by"),
                    minutes(r.get("best_bid_age")), minutes(r.get("best_ask_age"))]
            for k, v in enumerate(line):
                ws.set(2 + i, 1 + k, v, fmt=fmt if k in (4, 6, 8, 10, 13, 14) else ("#,##0.0" if k in (11, 12, 18, 19) else None))
        ws.autosize()
        bs = wb.add_sheet("Brokerlar")
        bs.row(1, 1, ["Ürün", "Enstrüman", "Broker", "Bid", "Bid saati", "Bid yaşı (dk)", "Bid bayat", "Ask", "Ask saati", "Ask yaşı (dk)",
                      "Ask bayat"], bold=True, fill="E7E6E6")
        n = 2
        for r in data["board"]:
            fmt = "#,##0.00" if r["unit"] == "pct" else "#,##0.0"
            for b in r.get("brokers") or []:
                line = [r["product"], r["label"], b["by"], b["bid"], b["bid_time"], minutes(b["bid_age"]), "bayat" if b["bid_stale"] else "",
                        b["ask"], b["ask_time"], minutes(b["ask_age"]), "bayat" if b["ask_stale"] else ""]
                for k, v in enumerate(line):
                    bs.set(n, 1 + k, v, fmt=fmt if k in (3, 7) else ("#,##0.0" if k in (5, 9) else None))
                n += 1
        bs.autosize()
        ls = wb.add_sheet("Kayıt")
        ls.row(1, 1, ["Tarih", "Saat", "Kimden", "Kaynak", "Mesaj", "Ürün", "Tür", "Enstrüman", "Olay", "Bid", "Ask", "İşlem / seviye",
                      "Birim", "Not", "Giren", "Taraf"], bold=True, fill="E7E6E6")
        for i, q in enumerate(data["rows"]):
            fmt = "#,##0.00" if q.get("unit") == "pct" else "#,##0.0"
            line = [date_to_serial(_dt.date.fromisoformat(q["date"])), q["time"], q.get("sender") or "", q.get("source") or "",
                    q.get("raw") or "", q.get("product") or "", kinds.get(q.get("kind"), q.get("kind") or ""), q.get("label") or "",
                    events.get(q.get("event"), q.get("event") or ""), q.get("bid"), q.get("ask"), q.get("price"),
                    ("%" if q.get("unit") == "pct" else "bp") if q.get("ok") else "", q.get("note") or "",
                    names.get(q.get("created_by"), q.get("created_by") or ""), {"biz": "Biz", "broker": "Broker"}.get(q.get("party") or "", "")]
            for k, v in enumerate(line):
                ls.set(2 + i, 1 + k, v, fmt="dd.mm.yyyy" if k == 0 else (fmt if k in (9, 10, 11) else None))
        ls.autosize()
        day, last = _dt.date.fromisoformat(data["date"]), _dt.date.fromisoformat(data["to"])
        name = "BrokerChat_%s.xlsx" % day.strftime("%Y.%m.%d") if not data["ranged"] else \
            "BrokerChat_%s-%s.xlsx" % (day.strftime("%Y.%m.%d"), last.strftime("%Y.%m.%d"))
        return wb.to_bytes(), name

    def delete_trade(self, user: str, trade_id: int) -> Dict[str, Any]:
        user = self.require_user(user)
        ids = self.store.delete_trade(int(trade_id), user)
        if not ids:
            raise ServiceError("işlem bulunamadı", 404)
        self.et.call_at(EngineThread.WRITE, self._sync_blotter)
        self.bump()
        return {"deleted": ids}


def _add_dv01_columns(data: Dict[str, Any], buckets: Dict[int, Tuple[float, float]], loc) -> None:
    """The forward buckets of the trades sheet with their DV01 ($) on the right: buys, sells, net - split
    between the buckets as the sheet splits the amounts (the sheet itself has no DV01 there)."""
    rows, rnums = data.get("rows") or [], data.get("r") or []
    if not rows or not buckets:
        return

    def numcell(v: float, bold: bool = False) -> Dict[str, Any]:
        if abs(v) < 0.5:
            return {"t": "-", "v": 0.0, "k": "n", "al": "c"}
        cell = {"t": ("+" if v > 0 else "") + numfmt.format_value(round(v), "#,##0", loc), "v": v, "k": "n",
                "c": "pos" if v > 0 else "neg"}
        if bold:
            cell["b"] = 1
        return cell

    head = {1: ["DV01 ($)", "", ""], 2: ["Buy", "Sell", "Net"], 3: ["", "", ""]}
    for i, r in enumerate(rnums):
        if r in head:
            rows[i].extend({"t": t, "k": "s", "b": 1, "f": "hd"} if t else {"t": "", "k": ""} for t in head[r])
        elif r in buckets:
            buy, sell = buckets[r]
            rows[i].extend([numcell(buy, r == 20), numcell(sell, r == 20), numcell(buy + sell, True)])
        else:
            rows[i].extend([{"t": "", "k": ""}] * 3)
    data["c"] = list(data.get("c") or []) + ["DV01 B", "DV01 S", "DV01 N"]
    data["added"] = int(data.get("added") or 0) + 3                 # columns that are not cells of the sheet


def _lift_title(data: Dict[str, Any]) -> Optional[str]:
    """If the block starts with the sheet's own caption row (one bold / merged text cell above a header
    row), take it out of the table and return it: it becomes the panel title."""
    rows = data.get("rows") or []
    if len(rows) < 2:
        return None
    filled = [c for c in rows[0] if not c.get("sk") and c.get("t")]
    if len(filled) != 1:
        return None
    c = filled[0]
    if c.get("k") != "s" or c.get("i"):
        return None
    if not (c.get("b") or c.get("f") == "hd" or c.get("cs", 1) > 1):
        return None
    if any(x.get("rs", 1) > 1 for x in rows[0]):
        return None
    if sum(1 for x in rows[1] if not x.get("sk") and x.get("t")) < 2:
        return None
    title = c["t"].strip()
    del rows[0]
    del data["r"][0]
    return title or None


def _pick_columns(data: Dict[str, Any], cols: Sequence[str]) -> None:
    """A table's columns in the order a page wants them (``["A", "B", "D", "M", ...]`` by column letter; one the
    table does not have - left out as empty, hidden - is skipped, one not named is not shown).  Every cell keeps its
    column letter, so an input is still typed into its own cell; a span across columns is not kept."""
    have = data.get("c") or []
    order = [have.index(c) for c in cols if c in have]
    if not order or order == list(range(len(have))):
        return
    data["rows"] = [[row[j] for j in order] for row in data["rows"]]
    for row in data["rows"]:
        for cell in row:
            if isinstance(cell, dict):
                cell.pop("cs", None)
    data["c"] = [have[j] for j in order]
    data.pop("fz", None)                         # (frozen columns counted the sheet's order)


_ASCII_TR = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")


def _all_done(futs: List["concurrent.futures.Future"]) -> "concurrent.futures.Future":
    """A future that is done when all of ``futs`` are (each one's result or error is read from it)."""
    out: "concurrent.futures.Future" = concurrent.futures.Future()
    if not futs:
        out.set_result(None)
        return out
    left = [len(futs)]
    lock = threading.Lock()

    def one(_f) -> None:
        with lock:
            left[0] -= 1
            last = left[0] == 0
        if last:
            out.set_result(None)

    for f in futs:
        f.add_done_callback(one)
    return out


def _missing(r: Dict[str, Any], error: str, status: int) -> Dict[str, Any]:
    """A table asked for that is not there (any more), or not this user's to see."""
    return {"view": r["view"], "panel": r["panel"], "missing": True, "status": status, "error": error}


def _panel_answer(r: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    """One table of a page's answer (see ``Service.panels_future``)."""
    base = {"view": r["view"], "panel": r["panel"], "gen": res.get("gen"), "as": res.get("as")}
    if res.get("unchanged"):
        return dict(base, unchanged=True)
    entry = next((p for p in res.get("panels") or [] if p.get("id") == r["panel"]), None)
    if entry is None:
        if r["panel"] in {x.rsplit(":", 1)[0] for x in res.get("ids") or []}:
            return dict(base, unchanged=True)             # (on the page, not changed since)
        return _missing(r, "bu tablo artık yok: sayfasında bulunamadı", 404)
    if (r["rows"] or r["cols"]) and entry.get("type") in ("table", "notes") and isinstance(entry.get("data"), dict):
        entry = dict(entry, data=_pick_part(entry["data"], r["rows"], r["cols"]))
    tab = ""
    for sec in res.get("sections") or []:
        if r["panel"] in sec.get("panels", []):
            tab = sec.get("title") or ""
            break
    return dict(base, entry=entry, book=res.get("book"), page=res.get("title"), tab=tab)


def _row_label(row: List[Dict[str, Any]]) -> Optional[str]:
    """The name of a row: its first text from the left - a tenor, an ISIN, a pair (numbers and dates before it are
    passed over: the RET table's day count stands left of its tenor).  ``None``: the row has no text."""
    for c in row:
        if not isinstance(c, dict) or c.get("sk") or c.get("k") != "s":
            continue
        t = " ".join(str(c.get("t") or "").split())
        if t:
            return t
    return None


def _header_row(row: List[Dict[str, Any]]) -> bool:
    """A caption row (as the browser takes one: two or more texts, most of them bold or captions, none an input)."""
    n = strong = 0
    for c in row:
        if not isinstance(c, dict) or c.get("sk") or not c.get("t"):
            continue
        if c.get("k") != "s" or c.get("i"):
            return False
        if c.get("c") or (c.get("f") and c.get("f") not in ("hd", "sub")):
            return False
        n += 1
        if c.get("b") or c.get("f") == "hd":
            strong += 1
    return n >= 2 and strong * 2 >= n


def _caption_rows(rows: List[List[Dict[str, Any]]], nums: List[Any]) -> set:
    """The rows at the top of a table that name its columns (a lone title row above them too): a part of the table
    keeps them."""
    out = set(i for i, r in enumerate(nums) if r == 0)
    for i, row in enumerate(rows):
        if i in out:
            continue
        if len(rows) > 1 and _header_row(row) and len(out) < 3:
            out.add(i)
        elif i == 0 and sum(1 for c in row if isinstance(c, dict) and not c.get("sk") and c.get("t")) <= 1:
            out.add(i)
        else:
            break
    return out


def _pick_part(data: Dict[str, Any], rows: Sequence[Any], cols: Sequence[str]) -> Dict[str, Any]:
    """Part of a table - a launchpad item's own choice - as a new table (the page's kept one is not changed).

    ``rows``: each a row's label (its first text from the left) or its number in the sheet; the caption rows at the
    top always stay.  ``cols``: column letters.  Both keep the table's own order.  A merged cell keeps the part of it
    that is still there; when its first cell went, what it shows moves to the first one left (read only then: typing
    there would write another cell).  Nothing of either left: the whole table, marked ``part_missing``."""
    src = data.get("rows") or []
    width = len(src[0]) if src else 0
    letters = list(data.get("c") or [])
    nums = list(data.get("r") or [])
    keep_c = list(range(width))
    missing = False
    if cols and len(letters) == width:
        want = set(cols)
        picked = [j for j in range(width) if letters[j] in want]
        if picked:
            keep_c = picked
        else:
            missing = True
    keep_r = list(range(len(src)))
    if rows:
        numbers = {x for x in rows if isinstance(x, int)}
        labels = {" ".join(x.split()) for x in rows if isinstance(x, str)}
        heads = _caption_rows(src, nums)
        body = [i for i in range(len(src)) if i not in heads and ((i < len(nums) and nums[i] in numbers)
                                                                  or _row_label(src[i]) in labels)]
        if body:
            keep_r = sorted(heads | set(body))
        else:
            missing = True
    new_r = {i: k for k, i in enumerate(keep_r)}
    new_c = {j: k for k, j in enumerate(keep_c)}
    out_rows: List[List[Dict[str, Any]]] = [[{"t": "", "k": ""} for _ in keep_c] for _ in keep_r]
    for i, row in enumerate(src):
        for j, cell in enumerate(row):
            if not isinstance(cell, dict) or cell.get("sk"):
                continue
            rs, cs = int(cell.get("rs") or 1), int(cell.get("cs") or 1)
            rr = [new_r[x] for x in range(i, i + rs) if x in new_r]
            cc = [new_c[y] for y in range(j, j + cs) if y in new_c]
            if not rr or not cc:
                continue
            copy = {k: v for k, v in cell.items() if k not in ("rs", "cs")}
            if i not in new_r or j not in new_c:
                for k in ("i", "o", "m", "ik"):
                    copy.pop(k, None)
            if len(rr) > 1:
                copy["rs"] = len(rr)
            if len(cc) > 1:
                copy["cs"] = len(cc)
            out_rows[rr[0]][cc[0]] = copy
            for a in rr:
                for b in cc:
                    if (a, b) != (rr[0], cc[0]):
                        out_rows[a][b] = {"sk": 1}
    out = {k: v for k, v in data.items() if k not in ("rows", "r", "c", "fz", "hc")}
    out["rows"] = out_rows
    if nums:
        out["r"] = [nums[i] for i in keep_r if i < len(nums)]
    if letters:
        out["c"] = [letters[j] for j in keep_c if j < len(letters)]
    fz = data.get("fz") or 0
    if fz:
        n = sum(1 for j in keep_c if j < fz)
        if 0 < n < len(keep_c):
            out["fz"] = n
    if missing:
        out["part_missing"] = True
    return out


def _column_captions(data: Dict[str, Any], captions: Dict[str, str]) -> None:
    """A caption row of the dashboard's own above a table whose columns the workbook left unnamed
    (``{"F": "USDTRY spot", ...}`` by column letter).  It belongs to no cell of the sheet: its row number is 0."""
    data["rows"].insert(0, [{"t": captions.get(c, ""), "k": "s", "b": 1, "f": "hd"} for c in data.get("c") or []])
    data["r"].insert(0, 0)


def _to_json(v: Any) -> Any:
    if type(v) is XlError:
        return v.code
    return v


def _from_json(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def _same_value(a: Any, b: Any) -> bool:
    """The same cell value: equal numbers (to the last digits a number typed again may differ in), or equal anything else."""
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))
    return type(a) is type(b) and a == b
