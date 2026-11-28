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
import logging
import math
import os
import queue
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Tuple
from urllib.parse import quote as _quote

from . import aswfx
from . import auth
from . import blotter as bl
from . import ppkcurve as pk
from . import pricing as pr
from . import quotelog as ql
from . import bonds as bd
from . import borsaspread as bsp
from . import brokerchat as bc
from . import datecells
from . import entry
from . import extras as ex
from . import layout as lay
from . import quotes as qt
from . import rvfair
from . import shortcuts
from . import swaption as sw
from . import tradehint as th
from . import volcarry as vc
from .books import Book, formula_text, load_books, snapshot_today
from .config import Settings
from .inputs import InputError, parse_amount, parse_clipboard, parse_date, parse_input, parse_number, yearless
from .marketdata import ReplayProvider
from .marketdata.replay import snapshot_from_model
from .render import Renderer
from .store import Store, now_iso, user_key
from .views import layout as view_layout, load_views
from .xl import numfmt
from .xl.engine import Calc, Clock, big_stack_thread
from .xl.errors import XlError
from .xl.model import COLS, a1, parse_a1, parse_range
from .xl.tokenizer import col_to_index, index_to_col
from .marketdata.base import INVALID_FIELD, INVALID_SECURITY, NOT_APPLICABLE
from .xl.values import XlArray, date_to_serial, serial_to_date, to_num

log = logging.getLogger("tto")

RET_TENORS =["ON", "TN", "1W", "2W", "3W", "1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y", "18M", "2Y"]
RET_FIRST_ROW = 33


def ret_changes(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What an upload of the RET curve changed, tenor by tenor: ``[{"tenor", "bid", "ask"}]`` - the moves in bp (a side
    without a number before or after: ``None``); tenors that did not move are left out."""
    was = {r["tenor"]: r for r in before}
    out = []
    for r in after:
        b = was.get(r["tenor"]) or {}
        move: Dict[str, Any] = {"tenor": r["tenor"]}
        moved = False
        for side in ("bid", "ask"):
            x, y = b.get(side), r.get(side)
            if type(x) is float and type(y) is float:
                d = round((y - x) * 10000.0, 2) + 0.0          # (no −0)
                move[side] = d
                moved = moved or abs(d) >= 0.005
            else:
                move[side] = None
                moved = moved or x != y
        if moved:
            out.append(move)
    return out


def _payer_plus(leg: Dict[str, Any]) -> Optional[float]:
    """The DV01 of an OIS leg with the desk's sign: paying fixed is plus, receiving is minus."""
    d = leg.get("dv01")
    if type(d) is not float:
        return None
    return d if leg.get("dir") == "B" else -d


def _vs_mid(cost: Any) -> Optional[float]:
    """What an OIS trade is worth against mid ("Mid'e göre": + better than mid, in its favour; − worse) from its stored
    cost (``cost_bp`` / ``cost_usd``: + worse than mid, paid - kept so, old trades read the same)."""
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return None
    return 0.0 - cost                                   # (0.0 - 0.0 is 0.0, not -0.0)


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400, data: Optional[Dict[str, Any]] = None):
        Exception.__init__(self, message)
        self.status = status
        self.data = data                    # more for the page beside the message (the error of each field of a form)


class EngineThread(object):
    """Runs every calculation on one thread with a large stack (formula chains recurse deeply).

    Work waits in order of priority, first come first served within one: what a user typed goes before the header
    strip, the header before a page, a page before the background (the watch lists, warming up).

    ``wrote`` is called on the thread at the end of every WRITE job - before its caller has the answer and before the
    next job starts (the service's: a new generation, :meth:`Service._wrote`) - unless the job said it changed nothing
    (:meth:`wrote_nothing`)."""

    WRITE, HEADER, VIEW, BACKGROUND = 0, 1, 2, 3
    _STOP = 99

    def __init__(self, name: str = "tto-engine", wrote: Optional[Callable[[], None]] = None):
        self._q: "queue.PriorityQueue" = queue.PriorityQueue()
        self._seq = itertools.count()
        self._busy_since = 0.0                 # when the job running now began (0: idle)
        self._wrote = wrote
        self._nothing = False                  # the WRITE job running now changed nothing (wrote_nothing)
        # a big stack: long chains are evaluated in one go (engine.DEEP_LIMIT deep) instead of unwound and restarted
        self._t = big_stack_thread(self._loop, name, daemon=True)

    def _loop(self) -> None:
        while True:
            priority, _, item = self._q.get()
            if item is None:
                return
            fut, fn, args, kw = item
            if not fut.set_running_or_notify_cancel():
                continue
            self._busy_since = time.time()
            try:
                fut.set_result(self._run(priority, fn, args, kw))
            except BaseException as exc:  # noqa: BLE001 - delivered to the caller
                fut.set_exception(exc)
            finally:
                self._busy_since = 0.0

    def _run(self, priority: int, fn: Callable, args: tuple, kw: Dict[str, Any]) -> Any:
        self._nothing = False
        try:
            return fn(*args, **kw)
        finally:
            # (a write that failed half way may have changed something too)
            if priority == self.WRITE and self._wrote is not None and not self._nothing:
                self._wrote()

    def wrote_nothing(self) -> None:
        """Said on the thread by the WRITE job running now when it changed nothing (the input formulas' round, the
        market's tick with nothing new): no new generation after it."""
        self._nothing = True

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
#: which page a browser has a table of ("s": everybody's, "p": the user's own) and the mark of the user's own decimals
#: on it (decimals.py) - what an answer's ``as`` says
_AS = re.compile(r"^[sp](~[0-9a-f]{1,8})?$")


def _flag(v: Any) -> bool:
    """A yes / no of a request: true, 1, "true", "1", "evet" - the text "false" is a no."""
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "evet", "yes", "on")
    return bool(v)


def _names_an_option(text: str, options: Optional[Sequence[Any]], aliases: Optional[Dict[str, str]]) -> bool:
    """Whether a typed text is one of a list's items or a word for one (VİOP's "Spot"): that it is, never a shortcut."""
    from .inputs import _fold
    t = _fold(text.strip())
    return any(_fold(str(o)) == t for o in options or ()) or any(_fold(str(w)) == t for w in aliases or {})


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
        self.ops.check_folder()                          # (a data folder on a network drive: said loud - datadir.py)
        # where the long calculations are - the quant fit, the ML models, the backtest, the history sync - and the time
        # left from the last runs (progress.py: the top bar's "Hesap")
        from .progress import Progress
        self.progress = Progress(self.store)
        # the desk's alarms: set once, they ring for everyone; the system's own (deskalarms.py)
        from .deskalarms import DeskAlarms
        self.desk_alarms = DeskAlarms(self)
        # (a write done there moves the generation before anything after it reads it: _wrote)
        self.et = EngineThread(wrote=self._wrote)
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
        # who is at the desk - online, away, offline -, when each was last seen and last signed in (presence.py: the top
        # bar's "● 3 çevrimiçi"); a change of somebody's state tells the open pages as a desk change does (no generation)
        from .presence import Presence
        self.presence = Presence(self.store, on_change=self.nudge,
                                 on_error=lambda exc: self.ops.failure("çevrimiçi durumu", exc))
        self._overlays: Dict[Tuple[str, str], Dict[Tuple[int, int], Any]] = {}
        self._retired: Dict[str, set] = {}
        # pages and headers kept per calculation (see view_future): key -> what was made, panel by panel
        self._renders: Dict[Tuple, Dict[str, Any]] = {}
        self._private_users: set = set()                 # users with inputs of their own (their pages are theirs)
        self._render_lock = threading.Lock()
        # the ASW history on the offshore curve: its quote arrays per calculation, past days worked out (_asw_hist_fx)
        self._hist_fx_kept: Dict[str, Dict[str, Any]] = {}
        self._hist_fx_rows: Dict[Tuple, Tuple[List[Optional[float]], List[str]]] = {}
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
        self.decimals = None                             # each user's own decimals (decimals.py), below
        self.et.call(self._setup, provider)
        from .history import History
        self.history = History(self)
        # the watch lists and the alarms: read again whenever the market or an input moved
        from .watch import Watch
        self.watch = Watch(self)
        try:
            # items and alarms an earlier version kept on a cell of a meeting's row: anchored to that meeting, once
            self.et.call(self.watch.anchor_meetings_once)
        except Exception as exc:  # noqa: BLE001 - the start goes on (tried again at the next one)
            self.ops.failure("izleme: toplantı satırları", exc)
        try:
            # (once: items and alarms kept as cells of a bond's row or a VİOP contract's column follow that, not the cell)
            self.et.call(self.watch.anchor_kept)
        except Exception as exc:  # noqa: BLE001 - tried again at the next start; the dashboard opens anyway
            self.ops.failure("izleme listelerinin kâğıda / kontrata bağlanması", exc)
        # Spot / FX and FX vol: the option market's quotes of a pair, its smile and distribution, the vol monitor
        from .fx import Fx
        self.fx = Fx(self)
        # the desk's own corner: reports to the administrators, the chat (Sosyal), the agenda (Ajanda)
        from .desk import Desk
        self.desk = Desk(self)
        # Trades: the desk's and each trader's own trades with their MTM and P&L, apart from the desk's position
        # (tradebook.py; their own tables - nothing of the desk's reads them)
        from .tradebook import TradeBook
        self.tradebook = TradeBook(self)
        # Prop (prop.py): the top bar's position-size calculator and prop risk - to look at only, over Trades' tabs
        from .prop import Prop
        self.prop = Prop(self)
        try:
            # the İzleme alarms of the trades' targets and stops as the trades are now - once at the start (a restart, a
            # restored database, a trade deleted elsewhere): never one twice
            self.et.call(self.tradebook.sync_alarms)
        except Exception as exc:  # noqa: BLE001 - each change of a trade puts its own right; the dashboard opens anyway
            self.ops.failure("Trades: hedef / stop alarmları", exc)
        # quant signals (quant.py): statistics of the closes in a thread of their own, never on the engine thread
        from .quant import Quant
        self.quant = Quant(self)
        # each user's own calc sheets on the launchpads (calc.py): formulas over the workbooks' cells, never Bloomberg
        from .calc import CalcSheets
        self.calcsheets = CalcSheets(self)
        # the fair value RET (retfair.py): the desk's rule-based RET beside the published one, its flow suggestions
        from .retfair import RetFair
        self.retfair = RetFair(self)
        # DİBS RV · Genel (dibsgenel.py): the trading list's bonds on DİBS RV, DİBS ASW and a zero-coupon curve fitted live
        from .dibsgenel import DibsGenel
        self.dibsgenel = DibsGenel(self)
        # Kâğıt Fiyatlama (kagitfiyat.py): one fair level per bond, a quote around it, the good levels and how it was built
        from .kagitfiyat import KagitFiyat
        self.kagitfiyat = KagitFiyat(self)
        # Kâğıt Fiyat Yükleme (fiyatyukleme.py): the desk's list of bonds priced from the morning's auction or Bloomberg's
        # last trade, the spreads on them, saved as the desk's upload file
        from .fiyatyukleme import FiyatYukleme
        self.fiyatyukleme = FiyatYukleme(self)
        # Bugün (bugun.py): the morning screen - what wants attention, read from what the service holds
        from .bugun import Bugun
        self.bugun = Bugun(self)
        # inputs typed as formulas (=C60+7): evaluated by the calc sheets' machinery, again whenever what they read moved
        from .inputformula import InputFormulas
        formulas = InputFormulas(self)
        self.et.call(formulas.start)
        self.formulas = formulas
        try:
            # once: the trading list's bonds the ASW list does not have go onto it (it follows the trading list from now on)
            self.et.call(self._asw_follows_once)
        except Exception as exc:  # noqa: BLE001 - tried again at the next start; the dashboard opens anyway
            self.ops.failure("DİBS ASW listesinin trading listesiyle eşlenmesi", exc)
        # temporary copies of the calculator tables (copies.py): inputs of their own, in a layer over the user's calculation
        from .copies import Copies
        self.copies = Copies(self)
        with self._render_lock:
            self._private_users |= self.copies.users()          # (their pages hold their copies: their own)
        # each user's own number of decimals in the tables (decimals.py): put on the answers, never on the pages kept
        from .decimals import Decimals
        self.decimals = Decimals(self)
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
        if self.mode == "live":
            # a quote's age (marketdata/age.py): when the price a market cell shows last changed - its "qa" on the page
            from .marketdata.age import CellQuotes
            for bid, rn in self.renderers.items():
                rn.quotes = CellQuotes(self.books[bid], provider)
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
                                 options=inp.get("options"), view=v["id"], aliases=inp.get("aliases"),
                                 tenor=inp.get("tenor"))
                except (KeyError, ValueError):
                    continue
        tto = self.books.get("tto")
        if tto is not None:
            for ref in bl.input_ranges():
                tto.declare(ref, scope="shared", group="blotter", view="blotter")
            for ref in ("Forward!D2", "Forward!B163", "Forward!L163"):
                if tto.input_def(*tto.cell(ref)) is None:       # (declared by the page: as it says - a date's tenor)
                    tto.declare(ref, scope="user", group="fwd-pricer", view="forward")
        # the two-way tables (twoway.py): every value of a row can be typed, the last typed stands - their stores
        # declared as inputs now, before anything saved is read
        from .twoway import TwoWay
        self.twoway = TwoWay(self)
        asw = self.books.get("asw")
        if asw is not None and ex.FXC_SHEET in asw.model.sheet_index and "ASW" in asw.model.sheet_index:
            # the OIS quotes the ASW curve is built from are swapped for the FX swap curve in a calculation of its
            # own (ASW against FX swaps): the engine has to know what depends on them - not inputs of the page
            si = asw.model.sheet_index["ASW"]
            asw.engine.declare_inputs([(si, aswfx.ROW * COLS + aswfx.QUOTE_COL + k) for k in range(len(aswfx.TENORS))]
                                      + [(asw.model.sheet_index[ex.FXC_SHEET], ex.FXC_CURVE_ROW * COLS + col_to_index("D"))],
                                      group="asw-fx-curve")         # (and EK_FX's computed 18M par there: _asw_fx_calc)
            if not any(x.startswith(ex.ASW_HIST_NAME + ":") for x in asw.left_out):
                # ... and so are the history's (ASW against the offshore curve, day by day): its Bloomberg history blocks
                # as a whole - an array formula given an array writes it into its cells (_asw_hist_fx)
                anchors = sorted({a for a in aswfx.history_anchors(asw.model.sheets[si]) if a is not None})
                asw.engine.declare_inputs([(si, a) for a in anchors], group="asw-hist-fx")
        # the TRY curves between their quoted tenors, each user's choice (interp.py): Bootstrap (Murex) or PPK basamak - the
        # choice (a personal input) and the PPK cells the service fills; the desk's list of the points the curves are built
        # from (curvepoints.py, Ayarlar → Eğri noktaları: on the default list the workbook's own formulas, as before)
        from .curvepoints import CurvePoints
        from .interp import Interp
        self.curvepoints = CurvePoints(self)
        self.interp = Interp(self)
        self.interp.declare()
        self.interp.apply_list()
        # DV01 Risk → VaR (varrisk.py): the realized covariances of the OIS and offshore curves' DV01 buckets, made of the
        # history's closes and written into EK_VAR for the page's VaR formulas
        from .varrisk import VarRisk
        self.varrisk = VarRisk(self)
        self.varrisk.declare()
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
        for book in self.books.values():
            datecells.show_inputs(book)          # (a date input not formatted as one - a holiday list's empty rows)
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
        # Tüm Kâğıtlar: the desk's list of bonds (the bonds typed into the page's old own rows join it - once); each
        # bond keeps its row, across restarts too (UNI_KEPT)
        self._desk_lock = threading.Lock()
        kept = self.store.get(self.UNI_KEPT)
        self._uni_kept = isinstance(kept, dict)
        kept = kept if isinstance(kept, dict) else {}
        self._uni_rows: Dict[str, int] = {str(k): int(v) for k, v in (kept.get("rows") or {}).items()
                                          if isinstance(v, int) and not isinstance(v, bool)}
        self._uni_freed: Dict[int, str] = {int(k): str(v) for k, v in (kept.get("freed") or {}).items() if str(k).isdigit()}
        self._uni_note: Optional[Dict[str, Any]] = None
        self._uni_written: Dict[Tuple[int, int], Any] = {}
        self._uni_day: Optional[_dt.date] = None  # the day the rows were written for (past maturity: off the next day)
        self._uni_tried = time.time()            # the kinds Bloomberg has not told: asked again in BOND_RETRY
        self._migrate_own_bonds()
        bd.set_desk(self._desk_now(), owner=self)
        # what the rows of the lists of bonds hold goes with their bonds (rowkeys.py): a list found changed since the
        # values were last put right moves them now - before the engine has the desk's values
        from .rowkeys import RowKeys
        self.rowkeys = RowKeys(self)
        self.rowkeys.start()
        # shared inputs saved earlier (RET curve, calendars ...) - a desk value kept at a two-way member's own cell from
        # before the table was two-way first goes to the member's store (twoway.TwoWay.adopt_shared)
        for book in self.books.values():
            self.twoway.adopt_shared(book)
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
        self._copy_try_holidays()                # (the Borsa workbook's copy of the TRY holidays: as the TRY workbook has them)
        self._declare_saved_cells()
        self._private_users = set(self.store.users_with_inputs())
        self._sync_universe()
        self.rowkeys.roll()                      # (VİOP's gold contracts: changed while the dashboard was off?)
        self.interp.refresh_list()               # (a list of points that differs from the default: its curves before any)
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
            if cell in book.inputs or cell in self._retired_cells(book) or cell in book.twoway:
                # (a page's input already - shared ones included -, one that moved, or a two-way table's cell: a value
                # typed over it before is its row's typed value - twoway.TwoWay.adopt)
                continue
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
                      queue_size=s.bbg_queue, budget=s.bbg_budget)
        stand_in = os.environ.get("TTO_BLPAPI_MODULE") or None      # tests: a module to use in place of blpapi
        if s.bbg_isolate:
            from .marketdata.bbg_process import IsolatedBloombergProvider, IsolationError
            try:
                provider = IsolatedBloombergProvider(s.bbg_host, s.bbg_port, interval=s.bbg_interval or 0.0,
                                                     blpapi_name=stand_in, silent_restart=s.bbg_silent_restart, **common)
                # a helper gone silent is started again in market hours only (each new one gets the answers held here)
                provider.restart_allowed = self.ops.in_market
                self._kept_bloomberg(provider)
                self._tell_desk_hours(provider)
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
        self._tell_desk_hours(provider)
        provider.start()
        favour_reader()
        return provider

    def _kept_bloomberg(self, provider) -> None:
        """What an earlier run of today used and was answered (kept in the database by :meth:`_keep_bloomberg`): the
        daily data limit counts it - by kind and by key too -, Bloomberg's own daily limit still holds, and no answer
        is asked again until it is due (quotes included: cache first, docs/market-data.md)."""
        today = _dt.date.today().isoformat()
        self._bbg_kept_at = 0.0
        self._bbg_usage_kept = {}
        self._bbg_kept_day = today
        try:
            used = self.store.get("bbg.hits") or {}
            if not isinstance(used, dict):
                used = {}
            if used.get("day") == today:
                provider.carry_hits(int(used.get("hits") or 0))
            carry = getattr(provider, "carry_day", None)
            if carry is not None:
                usage = self.store.bbg_usage(today)
                self._bbg_usage_kept = dict(usage)
                carry(used.get("kinds") if used.get("day") == today else None, usage, used.get("limit") or None)
            provider.preload(self.store.bbg_answers(today))
        except Exception:  # noqa: BLE001 - a start from nothing, as before
            pass

    #: seconds between two keepings of the day's Bloomberg count and answers
    BBG_KEEP_EVERY = 30.0

    def _keep_bloomberg(self) -> None:
        """Keep the data points used today (by kind, by key), Bloomberg's own daily limit and the answers got since the
        last time (live: every ``BBG_KEEP_EVERY`` seconds and when the dashboard stops) - a restart the same day does
        not spend the daily data limit on them again."""
        prov = self.provider
        answers = getattr(prov, "answers", None)
        if answers is None:
            return
        today = _dt.date.today().isoformat()
        if getattr(self, "_bbg_kept_day", today) != today:
            self._bbg_kept_day = today
            self._bbg_usage_kept = {}
        try:
            st = prov.status() or {}
            self.store.put("bbg.hits", {"day": today, "hits": int(st.get("hits_today") or 0),
                                        "kinds": {k: int(v) for k, v in (st.get("kinds") or {}).items()},
                                        "limit": str(st.get("bbg_limit") or "")})
            got = answers(self._bbg_kept_at)
            if got:
                self.store.bbg_keep(today, got)
                self._bbg_kept_at = max(t for _, _, t in got)
            usage = getattr(prov, "usage", None)
            if usage is not None:
                kept = getattr(self, "_bbg_usage_kept", None)
                if kept is None:
                    kept = self._bbg_usage_kept = {}
                changed = [(k, n) for k, n in usage().items() if kept.get(k) != n]
                if changed:
                    self.store.bbg_usage_keep(today, changed)
                    kept.update(changed)
        except Exception:  # noqa: BLE001 - kept the next time
            pass

    # ------------------------------------------------------------------ the desk's hours for Bloomberg
    def _bbg_desk(self, holidays: bool = True) -> Tuple[str, str, Tuple[str, ...]]:
        """(open, close, the TR holidays as ISO days): when Bloomberg may be asked again - the administrators' setting
        (İzleme · Alarmlar → Masa alarmları → Ayarlar, ``ops.settings``), on the desk's days."""
        st = self.ops.settings()
        days: Tuple[str, ...] = ()
        if holidays and getattr(self, "watch", None) is not None and getattr(self, "books", None):
            try:
                days = tuple(sorted(self.et.call(self.watch.holidays)))
            except Exception:  # noqa: BLE001 - week days only meanwhile
                days = ()
        return str(st.get("bbg_open") or "08:00"), str(st.get("bbg_close") or "19:00"), days

    def _tell_desk_hours(self, provider=None) -> None:
        """Tell the Bloomberg provider the desk's hours when they changed (outside them: no refresh, no poll)."""
        prov = provider if provider is not None else self.provider
        setter = getattr(prov, "set_desk_hours", None)
        if setter is None:
            return
        args = self._bbg_desk(holidays=provider is None)
        if provider is None and args == getattr(self, "_bbg_desk_told", None):
            return
        self._bbg_desk_told = args
        setter(*args)

    def bbg_open_now(self) -> bool:
        """Whether Bloomberg may be asked again now (the history's syncs): the desk's hours on the desk's days, by the
        workbooks' clock (a test's simulated one).  Always in replay."""
        if self.mode != "live":
            return True
        book = self.books.get("tto")
        try:
            now = _dt.datetime(1899, 12, 30) + _dt.timedelta(days=float(book.engine.clock.now()))
        except Exception:  # noqa: BLE001 - no workbook clock: the machine's
            now = _dt.datetime.now()
        open_, close, _ = self._bbg_desk(holidays=False)
        from .ops import hhmm
        if not self.ops.market_day(now.date().isoformat()):
            return False
        lo, hi = hhmm(open_), hhmm(close)
        return lo is not None and hi is not None and lo <= now.time() < hi

    def _reread_market(self) -> None:
        """A new day: every cell that reads Bloomberg is worked out again when next read - the provider sees which keys
        are still used (a key is asked again only while it is read: yesterday's ranges and dates are left alone)."""
        for b in self.books.values():
            keys = b.engine.market_keys()
            if keys:
                b.engine.market_changed(keys)

    # ================================================================== lifecycle / events
    def start(self) -> None:
        if self._market_thread is None:
            self._market_thread = threading.Thread(target=self._market_loop, name="tto-market", daemon=True)
            self._market_thread.start()
            if self.mode == "live":
                threading.Thread(target=self._warmup_safe, name="tto-warmup", daemon=True).start()
            self.history.start()
            self.ops.start()
            self.presence.start()
            self.quant.start()
            self.warm()
            threading.Thread(target=self._build_ref_indexes, name="tto-refs", daemon=True).start()
            if getattr(self.settings, "history", True):
                # Kâğıt Fiyatlama's closes (a year of curves) made ahead, and again when the history changes
                threading.Thread(target=self.kagitfiyat.warm, name="tto-kagit", daemon=True).start()

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
        if not self._stop.is_set():
            # (the inputs of the copyable tables that feed Bloomberg: read-only in a copy - told by those references)
            self.et.submit_at(EngineThread.BACKGROUND, self.copies.prepare)

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
        self.presence.stop()                       # (every "last seen" not written yet: kept for the next start)
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
                    if day_changed and self.mode == "live":
                        # a new day: the cells that read Bloomberg are read again, so the provider knows what is still
                        # used - what is, is asked once today (in the desk's hours); yesterday's ranges are left alone
                        self.et.call_at(EngineThread.WRITE, self._reread_market)
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
                    if self.mode == "live":
                        self._tell_desk_hours()          # the desk's hours and holidays (Bloomberg's quiet hours)
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
        interp = getattr(self, "interp", None)
        if interp is not None and interp.listed():
            interp.refresh_list()                # (the list's curves follow the quotes they are made of)
        if not (changed or keys):
            self.et.wrote_nothing()              # (the clock's tick alone: no new generation, nobody told - as before)
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
                if self.rowkeys.roll_due():        # a new day, a gold code typed: VİOP's gold contracts changed?
                    rolled = self.et.submit(self.rowkeys.roll).result(timeout=60)
                    if rolled and (rolled["moved"] or rolled["dropped"] or rolled["scenarios"]):
                        self.bump()
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

    def _wrote(self) -> None:
        """The calculation thread, at the end of a WRITE job (an input typed or deleted, a paste, a scenario, the market
        ...): a new generation at once, before the next job there - a page - reads it.  The writer's ``bump`` tells
        the pages afterwards, from its own thread.

        Without it a page made in between - asked for after the write was applied, before that bump (the browser's
        refresh that the previous write's answer started) - took the generation from before the write and made what
        the write changed: a browser that had that generation took it all for unchanged, and every later answer too
        (what they made was the same), so the page never showed the write (24.11.2026: DİBS RV's bond moved to another
        row, its price still on the old row; typed back there, nothing was sent - it was what the page showed)."""
        with self._gen_lock:
            self.gen += 1

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
        goes to the browser; the database keeps only its hash.  A sign-in: its time and address are the account's
        "last login" (the address for the administrators' account list only), and the user is online."""
        now = self._now()
        token = auth.new_token()
        key = user_key(user)
        self.store.purge_sessions(auth.stamp(now))
        self.store.add_session(auth.token_hash(token), key, auth.stamp(now + _dt.timedelta(days=auth.SESSION_DAYS)), ip)
        self.store.update_account(key, last_login=auth.stamp(now), last_login_ip=ip)
        self.presence.signed_in(key, token)
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
            self.presence.signed_out(token)         # (offline for the others at once, unless another browser is open)
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
        keep = auth.token_hash(token) if token else None
        self.store.drop_sessions(key, keep=keep)
        self.presence.ended(key, keep)
        self.forget_sessions()
        return {"ok": True}

    # ------------------------------------------------------------------ the administrators' page
    def accounts(self, user: Optional[str]) -> Dict[str, Any]:
        """Every account for the administrators' page - with who is online now, when each was last seen (presence.py)
        and their last sign-in with its address (``last_login_ip``: this list only)."""
        self.require_admin(user)
        return {"accounts": self.presence.mark(self.store.accounts()), "pending": self.store.pending_count(),
                "admins": len(self.store.admins())}

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
        self.presence.ended(acc["name"], keep)

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
        self.presence.ended(acc["name"])

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
            rows = self.store.user_inputs(user, book.id)
            if book.twoway:
                # (a value kept at a two-way member's own cell from before - "Elle değer", or the input it was, with its
                # formula: its row's typed value, in the member's store; a formula moved is read in again at once)
                rows, moved = self.twoway.adopt(user, book, rows)
                if moved and self.formulas is not None:
                    self.formulas.reread()
            for (bid, ref), val in rows.items():
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
        vr = getattr(self, "varrisk", None)
        if vr is not None and book is vr.tto:
            vr.refresh()                         # (DV01 Risk's VaR: the realized covariances current with the history)
        if not user:
            interp = getattr(self, "interp", None)
            if interp is not None and book is interp.tto and interp.listed():
                interp.refresh_list()            # (the desk's list of points: everybody's curve reads its cells)
            return book.engine.shared
        ov = self._overlay(user, book)
        fx = self.formulas
        if fx is not None and fx.pending and user in fx.pending:
            fx.catch_up(user)                    # (back: their inputs' formulas evaluated over what is there now)
            ov = self._overlays.get((user, book.id), ov)
        interp = getattr(self, "interp", None)
        if interp is not None:
            interp.sync(user, book)              # (their curve choice: the PPK cells current, theirs where they are their own)
        if not ov and not book.engine.derived.get(user):
            return book.engine.shared
        if user not in book.engine.users:
            return book.engine.set_user_inputs(user, ov)     # (given back while the user was away: made again)
        return book.engine.user(user)

    # ------------------------------------------------------------------ who is here
    #: a user seen this recently (seconds) - or with a live-update stream open - is connected
    CONNECTED_WINDOW = 120.0

    def saw(self, user: Optional[str], token: Optional[str] = None) -> None:
        """A request of the user (the session gate tells every one, with its session ``token``: who is at the desk)."""
        if user:
            self._seen[user] = time.monotonic()
            if token:
                self.presence.request(user, token)

    def stream(self, user: Optional[str], delta: int, token: Optional[str] = None) -> None:
        """A live-update stream of the user (of the session ``token``) opened (+1) or closed (-1)."""
        if not user:
            return
        with self._gen_lock:
            n = self._streams.get(user, 0) + delta
            if n > 0:
                self._streams[user] = n
            else:
                self._streams.pop(user, None)
        self.saw(user)
        if token:
            self.presence.stream(user, token, delta)

    def presence_view(self, user: Optional[str]) -> Dict[str, Any]:
        """Who is at the desk - the top bar's list (presence.py): the same for everybody, no address."""
        return self.presence.listing(self.require_user(user))

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
        names |= {key[0] for book in self.books.values() for key in book.engine.layers}      # (a copy's: its user)
        names.discard("")                         # (a layer over everybody's calculation - the ASW history offshore)
        for name in names:
            if self._streams.get(name) or now - self._seen.get(name, -1e9) < limit:
                continue
            for book in self.books.values():
                book.engine.drop_user(name)
                self._overlays.pop((name, book.id), None)
            self.copies.drop(name)                    # (their temporary copies, their ASW history offshore: made again)
            self.interp.forget(name)                  # (their own PPK curve: made again)
            self._hist_fx_kept.pop(name, None)
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
        # the fair value RET's tenors whose value now differs from the published RET (the header's "RET güncellemesi var")
        fair = self.retfair.summary() if tto is not None and getattr(self, "retfair", None) is not None else None
        return {"mode": self.mode, "note": self.mode_note, "provider": prov, "gen": self.gen, "today": today,
                "ret": ret, "ret_fair": fair, "server_date": _dt.date.today().isoformat(),
                # today's trades of the desk said in the broker chat and not entered in Günlük İşlemler (the menu's badge)
                "chat_missing": self.chat_unbooked(),
                "books": {bid: {"title": b.title, "formulas": b.model.formula_count(),
                                "source": b.model.meta.get("source"), "left_out": list(getattr(b, "left_out", []))}
                          for bid, b in self.books.items()},
                "port": self.settings.port,
                "streams": len(self._listeners),            # live-update streams open (one per browser)
                # how fresh the data is, the calculation thread's queue, the last fault a loop survived (ops.py)
                "ops": self.ops.status(prov),
                # the long calculations under way (progress.py): the top bar's "Hesap" ({"busy": false, …} when idle)
                "progress": self.progress.view()}

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
        """The pages of the menu (and of the search box) - an administrators' page only for them - in the menu's order,
        each naming its group, its entry and tab (tto/navmenu.py: the desk's reorganization of 28.11.2026) and its hint."""
        from . import navmenu
        return navmenu.arrange(self._nav_pages(user))

    def _nav_pages(self, user: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every page the user gets, as each module adds its own (``navmenu.arrange`` puts them in the menu's order)."""
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
        # the morning screen (bugun.py): what wants attention on one page - first of the desk's own pages, right under
        # Masa in the menu
        pages.append({"id": "bugun", "title": "Bugün", "group": "Masa", "book": None, "sheet": None, "custom": True})
        if "tto" in self.books:
            pages.append({"id": "watch", "title": "İzleme · Alarmlar", "group": "Masa", "book": "tto", "sheet": None,
                          "custom": True})
            pages.append({"id": "heat", "title": "Eğri Hareketi", "group": "Masa", "book": "tto", "sheet": None, "custom": True})
            pages.append({"id": "blotter", "title": "Günlük İşlemler", "group": "Masa", "book": "tto",
                          "sheet": bl.SHEET, "custom": True})
            pages.append({"id": "broker", "title": "Broker Chat", "group": "Masa", "book": "tto", "sheet": None, "custom": True})
            # the trades followed on their own (tradebook.py): the desk's and each trader's, never the blotter's (Broker
            # Chat stays right under the blotter: its trades are the blotter's)
            pages.append({"id": "trades", "title": "Trades", "group": "Masa", "book": "tto", "sheet": None, "custom": True})
            # pages of the dashboard's own: what happened over time, and the settings behind it
            pages.append({"id": "eod", "title": "Gün Sonu Matrisi", "group": "Masa", "book": "tto", "sheet": None, "custom": True})
            pages.append({"id": "mpc", "title": "PPK Fiyatlama Geçmişi", "group": "TRY Faiz", "book": "tto", "sheet": None,
                          "custom": True})
            pages.append({"id": "vol", "title": "Realized Vol · Carry", "group": "TRY Faiz", "book": "tto", "sheet": None,
                          "custom": True})
            pages.append({"id": "spreads", "title": "Spread Geçmişi", "group": "TRY Faiz", "book": "tto", "sheet": None,
                          "custom": True})
            # Fiyatlama (pricing.py): an instrument at any start and maturity on the TRY curves both ways - right after
            # OIS · PPK in the menu
            at = next((i + 1 for i, p in enumerate(pages) if p["id"] == "ois"), len(pages))
            pages.insert(at, {"id": "fiyatlama", "title": "Fiyatlama", "group": "TRY Faiz", "book": "tto", "sheet": None,
                              "custom": True})
            # Swaption (swaption.py): a TRY OIS swaption to look at, its underlying Fiyatlama's - right after Fiyatlama
            pages.insert(at + 1, {"id": "swaption", "title": "Swaption", "group": "TRY Faiz", "book": "tto", "sheet": None,
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
        # Kâğıt Fiyatlama (kagitfiyat.py): the first entry of the Tahvil menu
        from . import kagitfiyat
        pages = kagitfiyat.menu(pages)
        # Kâğıt Fiyat Yükleme (fiyatyukleme.py): right after Kâğıt Fiyatlama
        from . import fiyatyukleme
        pages = fiyatyukleme.menu(pages)
        # DİBS RV: one entry of the menu - Genel (dibsgenel.py) and the two sheets, DİBS RV and DİBS ASW, as its tabs
        from . import dibsgenel
        return dibsgenel.menu(pages)

    # ================================================================== rendering
    #: pages / headers kept (per calculation: everybody without inputs of their own shares one)
    RENDERS_KEPT = 120

    def view(self, user: Optional[str], view_id: str, show_hidden: bool = False, locale: Optional[str] = None,
             since: Optional[int] = None, panels: Optional[List[str]] = None, as_: Optional[str] = None) -> Dict[str, Any]:
        if self.et.here():
            key = self._render_key(user, view_id, show_hidden, locale)
            return self._answer(self._render_job(None, key, user, view_id, show_hidden, locale, None), since, None, as_,
                                user)
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
        them of (``"s"``: the one everybody shares, ``"p"``: the user's own - and the mark of the user's own decimals
        their cells carry, decimals.py; an answer says ``as``); ``since`` counts only on the same one."""
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
                return _done(self._answer(rec, since, wanted, as_, user))
            jk = (key, user, gen, wanted)
            job = self._inflight.get(jk)
            if job is None:
                job = self.et.submit_at(EngineThread.VIEW, self._render_job, jk, key, user, view_id, show_hidden, locale, wanted)
                self._inflight[jk] = job
        return _then(job, lambda rec: self._answer(rec, since, wanted, as_, user))

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
                as_: Optional[str] = None, user: Optional[str] = None) -> Dict[str, Any]:
        """What the browser gets of a kept page (never changing what is kept) - ``user``'s own decimals on its cells
        (decimals.py: their mark in ``as``, so that a browser holding the page from before a change gets it whole)."""
        dec = self.decimals
        mark = dec.mark(user) if dec is not None and user else ""
        kind = ("p" if rec["key"][0] else "s") + mark
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
        if mark:
            out["panels"] = dec.apply(user, rec.get("book"), rec["key"][3], out["panels"])
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
        copies = self.copies.of_view(user, view_id) if user else {}      # (the user's temporary copies of its tables)
        if not key[0] and (calc is not book.engine.shared or copies):
            # a user with inputs (or copies) of their own the key did not know of (it never shares their page): theirs
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

        def part(pid: str, ptype: str, reusable: bool, make: Callable[[], Dict[str, Any]], on: Optional[Calc] = None) -> None:
            order.append(pid)
            types.append(ptype)
            o = old.get(pid)
            if want is not None and pid not in want:
                # not asked for (another tab): kept as it is, checked when it is asked for
                panels[pid] = o if o is not None else {"entry": None, "meta": None, "content": 0, "checked": -1, "at": 0.0}
                return
            panels[pid] = self._made(o, calc if on is None else on, gen, reusable, make)

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
            reusable = p["type"] in ("table", "notes", "chart", "custom") and not p.get("append") and not p.get("source") \
                and not p.get("curve") and not p.get("bonds") \
                and not any(s.get("curve") for s in (p.get("spec") or {}).get("series") or ())   # (EK_FX's: its 18M is the TRY book's)
            ptype = "table" if p["type"] == "generated" else p["type"]
            part(p.get("id"), ptype, reusable,
                 lambda p=p, sheet=sheet: self._panel(p, v, book, calc, R, loc, overlay, user, sheet, charts, show_hidden, explorer))
            for cp in copies.get(p.get("id"), ()):
                # the user's temporary copies of the table, right under it: each out of a layer of its own over ``calc``
                layer = self.copies.calc(user, cp, calc)
                part(cp.pid, "table", True,
                     lambda p=p, sheet=sheet, cp=cp, layer=layer: self.copies.entry(
                         p, v, cp, book, layer, R, loc, user, sheet, charts, show_hidden, explorer), layer)
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
        top.update(view_layout(v, [pid for pid, _ in shown], {pid: [cp.pid for cp in lst] for pid, lst in copies.items()}))
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
        return self._answer(self._render(None, key, user, view_id, show_hidden, locale, None, self.gen), None, None,
                            None, user)

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
            # (the page it has them of: "s" / "p", and the mark of the user's own decimals - _answer)
            kind = x.get("as") if isinstance(x.get("as"), str) and _AS.match(x["as"]) else None
            out.append({"key": key, "view": vid, "panel": pid, "rows": rows, "cols": cols, "all": x.get("all") is True,
                        "since": since, "as": kind, "keys": x.get("keys") is True})
        return out

    def client_quote(self, user: Optional[str], view_id: str, panel_id: str, row: Any = None, part: Any = None,
                     language: Optional[str] = None, role: Optional[str] = None) -> Dict[str, Any]:
        """"Kotasyon kopyala": a pricing table's quote for a client, as text to send (tto/quotes.py) - from the cells
        the table's ``client_quote`` names, as this user's own calculation has them (their inputs and "Elle değer"
        values: what their page shows).  ``row``: one row of a table of quotes (its row in the sheet; without it, all
        of its filled rows); ``part``: one of the quotes side by side (USDTRY | EURTRY); ``language``: "tr" / "en" -
        the numbers follow it (34,25 / 34.25)."""
        user = self.require_user(user)
        v = self.view_index.get(str(view_id or ""))
        if v is None:
            raise ServiceError("sayfa bulunamadı: %s" % view_id, 404)
        admin = (role == "admin") if role is not None else self._is_admin(user)
        if v.get("admin") and not admin:
            raise ServiceError("erişim yok: bu sayfa yalnızca yöneticilere açıktır", 403)
        p = next((x for x in v["panels"] if x.get("id") == panel_id), None)
        if p is None or not p.get("client_quote"):
            raise ServiceError("bu tabloda kotasyon yok: %s / %s" % (view_id, panel_id), 404)
        book = self._book(v["book"])
        sheet = p.get("sheet", v["sheet"])
        lang = "en" if str(language or "").lower() == "en" else "tr"

        def number(x: Any) -> Optional[int]:
            if x is None or x == "":
                return None
            try:
                return int(x)
            except (TypeError, ValueError):
                raise ServiceError("geçersiz satır / parça: %r" % (x,))

        row, part = number(row), number(part)

        def run() -> Tuple[str, Optional[Dict[str, Any]]]:
            calc = self._calc(user, book)
            fmts = book.model.numfmts

            def read(ref: str) -> Tuple[Any, str]:
                si, rc = book.cell(ref)
                st = book.model.sheets[si].styles.get(rc, 0)
                return calc.get(si, *divmod(rc, COLS)), (fmts[st] if st < len(fmts) else "General")

            text = qt.quote_text(p["client_quote"], read, sheet, lang, serial_to_date(book.engine.clock.today()), row, part)
            # the quote log (tto/quotelog.py): every copy is a quote given - its levels as the table has them now
            try:
                rec = ql.from_table(p["client_quote"], read, sheet, row, part, text,
                                    {"page": v["id"], "panel": str(panel_id), "panel_title": str(p.get("title") or "")})
            except Exception:  # noqa: BLE001 - the copy stands without its record
                log.warning("kotasyon defteri: %s / %s okunamadı", v["id"], panel_id, exc_info=True)
                rec = None
            return text, rec

        try:
            text, rec = self.et.call(run)
        except qt.QuoteError as exc:
            raise ServiceError(str(exc))
        out = {"text": text, "language": lang, "view": v["id"], "panel": panel_id, "row": row, "part": part}
        if rec is not None:
            try:
                out["log_id"] = self.store.add_quote_log(self.today_iso(), rec, "open", user)
            except Exception:  # noqa: BLE001 - the copy stands without its record
                log.warning("kotasyon defteri: kayıt yazılamadı", exc_info=True)
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
        if p.get("limit"):
            entry["limit"] = p["limit"]             # its first rows only; "Tümü (N)" shows the rest (view.js)
        if p.get("fit"):
            entry["fit"] = True                     # as wide as its table, never stretched (.panel.fit)
        if p.get("full"):
            entry["full"] = True                    # the page's whole width (a wide chart with a table under it)
        if p.get("card"):
            entry["card"] = p["card"]               # a click on ▸ opens the bond's card
        if p.get("flags"):
            entry["flags"] = p["flags"]             # ☆ / ★: onto / off the trading list
        if p.get("quote"):
            entry["quote"] = p["quote"]             # "Kota mesajı": its rows as a message to send
        if p.get("trade") and p["trade"].get("bid") and p["trade"].get("ask"):
            entry["trade"] = p["trade"]             # "İşlem gir" in the header: a row and a side as a trade to enter
        if p.get("client_quote"):
            # "Kotasyon kopyala": what the browser needs to offer it - its rows (one row's quote on a right click) and
            # its parts (USDTRY | EURTRY side by side); the text is made by client_quote
            cq = p["client_quote"]
            entry["client_quote"] = {k: cq[k] for k in ("rows",) if k in cq}
            if cq.get("parts"):
                entry["client_quote"]["parts"] = [qt.part_name(cq, k) for k in range(len(cq["parts"]))]
        if p.get("ranked"):
            entry["ranked"] = True                  # a ranking: a launchpad keeps a choice of its rows by number
        copies = getattr(self, "copies", None)
        if copies is not None and copies.offered(v["id"], p.get("id")):
            entry["copyable"] = True                # "Geçici kopya aç": a calculator whose inputs are the user's own
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
                if book.twoway:
                    # a two-way table (twoway.py): what its cells do, said under it - each group's note in ``tw`` as well:
                    # the page shows one that a table above it says already only once (view.js)
                    tw_notes = self.twoway.notes_for(book, sheet, p["range"])
                    tw_note = " ".join(tw_notes)
                    if tw_note and tw_note not in (entry.get("note") or ""):
                        entry["note"] = (entry["note"] + " " if entry.get("note") else "") + tw_note
                        entry["tw"] = tw_notes
                if p.get("tips"):
                    _cell_tips(entry["data"], book, calc, sheet, p["tips"])
                if p.get("lift", True):
                    own = _lift_title(entry["data"])
                    if own and not p.get("keep_title"):
                        entry["title"] = own
                if p.get("cols"):
                    _pick_columns(entry["data"], p["cols"])
                if p.get("rows"):
                    _pick_rows(entry["data"], p["rows"])      # (the twin of "cols": these rows, in this order - B15)
                if p.get("header"):
                    _column_captions(entry["data"], p["header"])
                if p.get("ppk") == "fra":
                    # the second view: the same rows on the PPK step curves (out of ``calc`` - a copy's too)
                    self._fra_ppk_columns(book, calc, entry["data"], loc)
                elif p.get("ppk") == "broken":
                    self._broken_ppk_columns(book, calc, entry["data"], loc)
                if p.get("append") == "asw_fx":
                    self._asw_fx_columns(book, user, entry["data"], loc)
                elif p.get("append") == "asw_hist_fx":
                    self._asw_hist_fx_columns(book, user, R, entry["data"], loc)
                elif p.get("append") == "fra_buckets":
                    self._fra_bucket_columns(book, calc, entry["data"], loc)
                elif p.get("append") == "fx_curve":
                    self._fx_curve_columns(book, self._asw_fx_calc(book, user)[0], entry["data"], loc,
                                           self._asw_fx_point(book, user))
                elif p.get("append") == "broker_bonds":
                    self._dibs_broker_columns(book, user, entry["data"], loc)
                elif p.get("append") == "dibs_live":
                    self._dibs_live_columns(book, user, entry["data"], loc)
                elif p.get("append") == "universe":
                    self._universe_columns(book, user, entry["data"], loc)
                elif p.get("append") == "borsa_spread":
                    self._borsa_spread_columns(book, calc, user, entry["data"], loc, p["range"])
                elif p.get("append") == "dv01_paste":
                    self._dv01_paste_column(user, entry["data"])
                if p.get("kontrol"):
                    # Masa's Kontrol strip: each chip leads to the table it checks, its rule in its tooltip (K5)
                    self._kontrol_chips(book, calc, entry["data"])
                if p.get("cols") and entry["data"].get("added"):
                    # the dashboard's own columns added above, named in "cols" by their caption, where the page lists
                    # them (Borsa Swap: the spreads right after BID % / ASK %); one it does not name stays at the end
                    have = entry["data"]["c"]
                    _pick_columns(entry["data"], [c for c in p["cols"] if c in have] + [c for c in have if c not in p["cols"]])
                if p.get("bonds"):
                    # a list of bonds: its rows without a bond left out, the bonds in the trading list's order (display only)
                    self._bond_rows(book, calc, sheet, p["bonds"], entry["data"])
                if p.get("freeze") is not None:
                    # the view's own frozen columns, in place of the workbook's: counted as the panel shows them
                    sh = book.model.sheets[book.model.sheet_index[sheet]]
                    _freeze_columns(entry["data"], p["freeze"],
                                    (lambda c: sh.col_hidden(col_to_index(c))) if show_hidden and sh.hidden_cols else None)
                hint = th.client(p.get("trade"), v["id"], p.get("id"))
                if hint:
                    entry["data"]["trade"] = hint   # its prices: right click, "İşlem gir" (trade_prefill)
            elif p["type"] == "chart" and p.get("ppk") == "interp":
                # the interpolation chart (OIS · PPK): both ways' overnight forward and 3M FRA strip, every horizon and
                # curve at once, out of the curves the FRA lists' PPK columns read - the user's own calculation
                from . import interpchart
                idx = book.model.sheet_index
                entry["data"], entry["choice"] = interpchart.panel(
                    self._try_curves(book, calc), lambda sheet, r, c: calc.get(idx[sheet], r, c), loc)
            elif p["type"] == "chart":
                spec = p.get("spec")
                if spec is None:
                    idx = p.get("chart", 0)
                    if idx < len(charts):
                        spec = charts[idx]
                on = calc
                if spec is not None and p.get("curve") == "fx":
                    # the workbook's chart once more, on the FX swap curve: its points and its fitted curve are the
                    # sheet's own, with the OIS quotes its curve is built from swapped for the FX swap implied rates
                    on, _ = self._asw_fx_calc(book, user)
                    spec = self._chart_as(spec, p.get("as") or {})
                if spec is not None and p.get("curve") == "hist":
                    # the ASW history: against OIS (the workbook's chart), the offshore curve or both - the user's choice
                    entry["data"], entry["pick"], extra = self._asw_hist_chart(book, user, calc, R, spec, loc, p)
                    entry["title"] = p.get("title") or entry["data"]["title"]
                    if extra:
                        entry["note"] = (entry.get("note") or "") + (" " if entry.get("note") else "") + extra
                elif spec is not None and on is None:
                    entry["data"] = R.chart(calc, dict(spec, series=[]), loc)
                    entry["note"] = "FX swap ima faizi yok (EK_FX): grafik çizilemedi"
                elif spec is not None:
                    entry["data"] = R.chart(on, spec, loc)
                    if any(s.get("curve") == "fx" for s in spec.get("series") or []):
                        self._fx_series(self._asw_fx_calc(book, user)[0], R, spec, entry["data"], loc)
                    entry["title"] = p.get("title") or entry["data"]["title"]
            elif p["type"] == "custom":
                entry["component"] = p.get("component")
            elif p["type"] == "generated":
                entry["type"] = "table"             # a table of the dashboard's own, from no range of a sheet
                if p.get("source") == "dibs_tape":
                    entry["data"] = self._tape_table(user, loc)
                elif p.get("source") == "dibs_trading":
                    entry["data"] = self._trading_table(user, loc)
                if p.get("freeze") is not None:
                    _freeze_columns(entry.get("data"), p["freeze"])      # (its first columns stay in view)
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
            h = book.twoway.get((si, r * COLS + c)) if book.twoway else None
            if h is not None and h.store and not h.member.own:
                mr, mc = divmod(h.member_cell[1], COLS)    # (a two-way store's formula: shown on its member's cell)
                if mr in rows and index_to_col(mc) in cols:
                    r, c = mr, mc
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
            return self._with_hand(self._header(user, locale), user)
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
                return _done(self._with_hand(self._header_answer(rec, since, as_), user))
            jk = (key, user, gen)
            job = self._inflight.get(jk)
            if job is None:
                job = self.et.submit_at(EngineThread.HEADER, self._header_job, jk, key, user, locale)
                self._inflight[jk] = job
        return _then(job, lambda rec: self._with_hand(self._header_answer(rec, since, as_), user))

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
                part = self._made(old, calc, gen, True, lambda: {k: v for k, v in self._header(user, locale).items() if k != "gen"})
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
        out: Dict[str, Any] = {"items": items, "gen": self.gen}
        badge = self.interp.badge(user, calc)
        if badge is not None:
            out["interp"] = badge                   # (a user on PPK basamak: every page says so in the top bar)
        if self._norm_on(calc):
            # the user's TLREF normalization on (OIS · PPK): their numbers are not the desk's - the top bar's personal
            # badge says so (the desk, 28.11.2026: A6); the values typed over formulas come with every answer ("hand")
            out["mine"] = {"norm": True}
        return out

    def _norm_on(self, calc: Any) -> bool:
        """Whether TLREF's normalization is on in this calculation (OIS_MAIN!M2, its ON cell: the switch on, with a date
        and a normal TLREF - tto/interp.py's ``norm_cell``)."""
        cell = getattr(getattr(self, "interp", None), "norm_cell", None)
        if cell is None or calc is None:
            return False
        try:
            return calc.get(cell[0], *divmod(cell[1], COLS)) == 1.0
        except Exception:  # noqa: BLE001
            return False

    def _hand_count(self, user: Optional[str]) -> int:
        """How many values this user typed over a workbook formula ("Elle değer") in the books loaded for them - read from
        the inputs in memory (no database read: the header is asked on every refresh)."""
        if not user:
            return 0
        n = 0
        for (who, bid), ov in list(self._overlays.items()):
            book = self.books.get(bid)
            if who != user or book is None:
                continue
            for cell in list(ov):
                d = book.inputs.get(cell)
                if d is not None and d.group == "adhoc" and cell[1] in book.model.sheets[cell[0]].fml:
                    n += 1
        return n

    def _with_hand(self, ans: Dict[str, Any], user: Optional[str]) -> Dict[str, Any]:
        """A header's answer with the user's count of values typed over formulas (``hand``, while there is one - also
        when the strip is unchanged: an answer without it says there is none)."""
        n = self._hand_count(user)
        return dict(ans, hand=n) if n else ans

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

    def cell_info(self, user: Optional[str], book_id: str, ref: str, locale: Optional[str] = None,
                  copy: Optional[str] = None) -> Dict[str, Any]:
        """A cell as the status bar tells it: its formula, value, input; ``copy``: as a temporary copy of the user's
        has it (its value out of the copy, its own value or the table's, why it is read-only there)."""
        return self.et.call(self._cell_info, user, book_id, ref, locale, copy)

    def _cell_info(self, user, book_id, ref, locale, copy=None) -> Dict[str, Any]:
        book = self._book(book_id)
        try:
            si, rc = book.cell(ref)
        except (KeyError, ValueError):
            raise ServiceError("hücre bulunamadı: %s" % ref, 404)
        r, c = divmod(rc, COLS)
        calc = self._calc(user, book)
        overlay = self._overlay(user, book) if user else None
        cp = layer = None
        if copy and user:
            cp = self.copies.find(user, copy)
            layer = self.copies.calc(user, cp, calc)
            calc, overlay = layer, layer.overlay
        loc = numfmt.get_locale(locale or self.settings.locale)
        cell = self.renderers[book.id].cell(calc, si, r, c, loc, overlay)
        key = (si, rc)
        tw = book.twoway.get(key)
        if tw is not None and tw.redirected:
            key = tw.store_cell                            # (a two-way member: its value is kept in its store)
        d = book.inputs.get(key)
        sheet = book.model.sheets[si]
        base = sheet.consts.get(rc)
        inp = None if d is None else {"scope": d.scope, "label": d.label, "kind": d.kind}
        if inp is not None and tw is not None and not tw.store:
            a = tw.group.anchor(tw.pos, overlay, book.engine.input_value)
            inp["twoway"] = {"group": tw.group.label, "member": tw.member.name,
                             "anchor": None if a is None else {"member": a.name, "ref": book.ref(*a.cells[tw.pos])}}
        if inp is not None and cp is not None:
            t = self.copies.tables.get((cp.view, cp.panel))
            why = None if t is None else (self.copies.readonly(t).get(key) if key in t.cells else "kopyanın girdisi değil")
            inp["copy"] = cp.n
            if why:
                inp["readonly"] = why
            elif layer.overlay.get(key, _NOT_SET) is not _NOT_SET and (tw is None or layer.overlay[key] is not None):
                inp["own"] = True                          # (the copy's own value; else the table's)
        e = self.formulas.entry(user, book.id, *key) if (self.formulas is not None and inp is not None) else None
        if e is not None and not inp.get("own"):
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
    #: TRY is kept three times - the TRY workbook's list (date and name; every WORKDAY of the workbook reads it), the ASW
    #: workbook's (dates) and the Borsa workbook's (dates: ``extras.BORSA_HOL_SHEET``, the BIST swaps' T+1 value date;
    #: its file has none, it starts as the TRY workbook's list - ``_copy_try_holidays``) - and edited as one list.  USD
    #: and EUR are the dashboard's own (``extras.HOL_SHEET``): the FX value dates skip the holidays of both currencies of a
    #: pair.  The first list of each is the one the TRY workbook's formulas read.  The USD workbook's US holidays (SIFMA:
    #: its SOFR / USD OIS sheets) and FOMC meetings are shown beside them, read only.
    HOLIDAY_LISTS = {"TRY": (("tto", "Motor", 361, 523, "A", "B"), ("asw", "ASW", 2, 200, "LR", None),
                             ("borsa", ex.BORSA_HOL_SHEET, ex.BORSA_HOL_FIRST, ex.BORSA_HOL_LAST, "A", None)),
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

    def _copy_try_holidays(self) -> None:
        """The Borsa workbook's copy of the TRY holiday list (its file holds none) is the TRY workbook's list as it stands
        - the file's days and what the desk saved -, row by row: the BIST swaps' T+1 value date skips the days the TRY OIS
        spot date does.  Made so when the service starts and when days of the TRY list are written or put back one by
        one (``_follow_try_holidays``); the settings page writes every copy itself.  Nothing is stored for it here (the
        copy's own days the desk saved, if any, give way to it)."""
        lists = {book.id: (book, cells) for book, cells in self._holiday_cells("TRY")}
        if "tto" not in lists or "borsa" not in lists:
            return
        (tto, src), (borsa, dst) = lists["tto"], lists["borsa"]
        calc = tto.engine.shared
        days = [calc.get(si, *divmod(rc, COLS)) for (si, rc), _ in src]
        days = [v if type(v) is float and 20000 < v < 80000 else None for v in days]
        engine = borsa.engine
        sets: Dict[Tuple[int, int], Any] = {}
        clears: List[Tuple[int, int]] = []
        for k, ((si, rc), _) in enumerate(dst):
            want = days[k] if k < len(days) else None
            held = engine.input_value[si]
            if want is None or _same_value(want, engine.base_value(si, rc)):
                if rc in held:
                    clears.append((si, rc))
            elif rc not in held or not _same_value(held[rc], want):
                sets[(si, rc)] = want
        for key in list(sets) + clears:
            if key not in borsa.inputs:
                borsa.declare(borsa.ref(*key), scope="shared", group="adhoc-shared")
        if clears:
            engine.clear_inputs(clears)
        if sets:
            engine.set_inputs(sets)

    def _follow_try_holidays(self, book: Book, cells: List[Tuple[int, int]]) -> None:
        """Days of the TRY workbook's holiday list written or put back one by one (the Motor page, a reset - the settings
        page writes every copy itself): the Borsa workbook's copy follows at once."""
        if book.id != "tto" or not cells:
            return
        src = next((c for b, c in self._holiday_cells("TRY") if b.id == "tto"), None)
        if src is not None and {dcell for dcell, _ in src} & set(cells):
            self._copy_try_holidays()

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
            serial = (float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool)
                      else parse_date(str(raw or ""), self._typed_today()))      # ("1/1": the next one)
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
        A change of the trading list (DİBS RV's ISINs) takes the ASW list and Tüm Kâğıtlar along (``follow``:
        :meth:`_follow_trading`).
        A cell of a two-way table (twoway.py) is kept in its member's store and empties the row's other typed value -
        the last typed wins; a row only blanked goes back to its default.
        """
        user = self.require_user(user)
        res = self.et.call_at(EngineThread.WRITE, self._set_inputs, user, book_id, items, allow_adhoc, lang or self.settings.locale, lenient)
        self._follow_trading(user, res)
        self.bump()
        res["gen"] = self.gen
        return res

    def _set_inputs(self, user, book_id, items, allow_adhoc, lang="tr", lenient=False) -> Dict[str, Any]:
        from . import meetings as mt
        from .inputformula import FormulaError
        book = self._book(book_id)
        if len(items) > 20000:
            raise ServiceError("çok fazla hücre")
        user_vals: Dict[Tuple[int, int], Any] = {}
        user_clear: List[Tuple[int, int]] = []
        shared_vals: Dict[Tuple[int, int], Any] = {}
        shared_clear: List[Tuple[int, int]] = []
        keyed: Dict[str, Dict[int, Optional[str]]] = {}    # a meeting calendar -> {slot: the date typed there (None: blank)}
        errors: List[str] = []
        skipped = 0
        user_forms: Dict[Tuple[int, int], Any] = {}      # cells typed as a formula: (sheet, rc) -> its entry
        shared_forms: Dict[Tuple[int, int], Any] = {}
        typed_dates: Dict[str, Dict[str, Any]] = {}      # dates typed as a shortcut: ref -> {typed, date, text}
        # a drop-down list Excel reads from a range (VİOP target's contracts, L97:X97) holds what those cells hold now
        calc = self._calc(user, book)
        # a two-way table's cells (twoway.py): each into its member's store - the last value of a row-side only -, the
        # row-side's other stores emptied once that value is taken; a row-side the write only blanks: all of its stores
        expanded, tw_clear, tw_blank = self.twoway.expand(book, items)
        quiet: set = set()                               # (stores the two-way tables emptied: not counted as written)
        for cell in tw_clear:
            d = book.inputs.get(cell)
            (shared_clear if d is not None and d.scope == "shared" else user_clear).append(cell)
            quiet.add(cell)

        def siblings(tw) -> None:
            # the member typed is its row-side's value now: the row-side's other stores go
            for cell in tw.siblings():
                d = book.inputs.get(cell)
                if d is not None and d.scope == "shared":
                    shared_vals.pop(cell, None)
                    shared_forms.pop(cell, None)
                    if cell not in shared_clear:
                        shared_clear.append(cell)
                else:
                    user_vals.pop(cell, None)
                    user_forms.pop(cell, None)
                    if cell not in user_clear:
                        user_clear.append(cell)
                quiet.add(cell)

        for it, tw, said in expanded:
            ref = it.get("ref")
            shown = said if tw is not None else ref        # (a two-way member's: the cell typed into, not its store)
            try:
                si, rc = book.cell(ref)
            except (KeyError, ValueError, AttributeError):
                errors.append("%s: hücre bulunamadı" % ref)
                continue
            raw = it.get("value")
            typed_dates.pop(str(shown), None)             # (typed again in the same write: the last one counts)
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
                    errors.append("%s: %s" % (shown, self.twoway.said(book, str(exc))))
                    continue
                # a two-way member's formula reading its own row-side: a cycle once it stands (the row-side's other
                # values are then worked out from it - a typed value it reads now is emptied by this write)
                ring = self.twoway.own_row_ring(book, tw, self.formulas.boxes(ent)) if tw is not None else None
                if ring:
                    from .twoway import ROW_CYCLE
                    errors.append("%s: %s" % (shown, ROW_CYCLE % " → ".join(ring)))
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
                if tw is not None:
                    siblings(tw)
                continue
            user_forms.pop((si, rc), None)                # (a value typed after a formula in one write: the value)
            shared_forms.pop((si, rc), None)
            cal = mt.key_of(book, si, rc)
            if cal is not None:
                # a meeting's date: the list changes through the calendar only, which moves what belongs to a meeting;
                # a day typed without its year is the next one (the desk, 28.11.2026)
                day = parse_date(raw, serial_to_date(book.engine.clock.today())) if yearless(raw) else None
                try:
                    got = self.history.parse_dates([day if day is not None else it.get("value")])
                except ValueError as exc:
                    errors.append("%s: %s" % (ref, exc))
                    continue
                keyed.setdefault(cal.id, {})[rc // COLS - cal.first] = got[0] if got else None
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
            # (a two-way member's value is read in its own cell's format: its store keeps it)
            fsi, frc = tw.member_cell if tw is not None else (si, rc)
            fxf = book.model.sheets[fsi].styles.get(frc, 0)
            fmt = book.model.numfmts[fxf] if fxf < len(book.model.numfmts) else "General"
            options = book.options_for(si, rc, calc)
            if (isinstance(raw, str) and d.kind not in ("amount", "list") and (d.kind == "date" or numfmt.is_date_format(fmt))
                    and shortcuts.date_shortcut(raw) is not None and not _names_an_option(raw, options, d.aliases)):
                # a date typed as the desk says it ("1A", "ay sonu", "IMM", "+5"): the date it stands for is stored -
                # from the cell's natural start, on its pair's calendar; what was typed goes back for the tooltip
                pending = dict(shared_vals)
                pending.update(user_vals)                         # (a start typed in the same block counts)
                try:
                    day = self._shortcut_date(user, book, fsi, frc, d, raw, calc, pending)
                except (KeyError, ValueError, TypeError, OverflowError) as exc:
                    errors.append("%s: kısayol anlaşılamadı: %r (%s)" % (shown, raw, exc))
                    continue
                if day is not None:
                    text = serial_to_date(day).strftime("%d.%m.%Y")
                    typed_dates[str(shown)] = {"typed": " ".join(raw.split()), "date": day, "text": text}
                    raw = text                                    # (a list of days kept as text takes it as its item)
            # a day typed without its year ("26/12", the desk 28.11.2026): the next such day - from the start of the
            # period it ends on, when that is later -, the last one in a cell that asks about the past (datecells.PAST)
            today = past = after = None
            if (yearless(raw) and d.kind not in ("amount", "text", "check")
                    and (d.kind == "date" or numfmt.is_date_format(fmt) or options)):
                pending = dict(shared_vals)
                pending.update(user_vals)
                today, past, after = self._typed_day_rule(book, fsi, frc, d, calc, pending)
            try:
                val = parse_input(raw, numfmt.is_percent_format(fmt), numfmt.is_date_format(fmt),
                                  d.kind, options, lang, d.aliases, today, bool(past), after)
            except InputError as exc:
                errors.append("%s: %s" % (shown, exc))
                continue
            if today is not None and type(val) is float and 20000 < val < 80000:
                typed_dates[str(shown)] = {"typed": " ".join(raw.split()), "date": val,
                                           "text": serial_to_date(val).strftime("%d.%m.%Y")}
            elif today is not None and isinstance(val, str) and val != raw and parse_date(val) is not None:
                typed_dates[str(shown)] = {"typed": " ".join(raw.split()), "date": parse_date(val), "text": val}
            if d.scope == "shared":
                if val is None and (rc in sheet.fml or tw is not None):
                    shared_clear.append((si, rc))      # a desk input with a formula default: the formula, for everybody
                else:
                    shared_vals[(si, rc)] = val
            elif val is None and (rc in sheet.fml or d.group == "adhoc" or tw is not None):
                # blanking a formula default = back to the formula; blanking a value typed over any other cell
                # ("elle değer") = back to what the workbook holds there; a two-way store: empty again
                user_clear.append((si, rc))
            else:
                user_vals[(si, rc)] = val
            if tw is not None:
                siblings(tw)
        for cell in self._cross_typed_forwards(user, book, calc, user_vals, user_clear):
            if cell not in user_clear:
                user_clear.append(cell)                 # (ÇAPRAZ FORWARD's currency changed: its typed forwards go)
            quiet.add(cell)
        calendar = None
        typed_n = 0
        for cid, typed in keyed.items():
            # first, so that what was typed with the dates lands on the meetings as the new list has them
            cal = mt.BY_ID[cid]
            rows = mt.slot_dates(book, cal)
            typed = self._typed_dates(cal, rows, typed, errors)
            if not typed:
                continue
            try:
                if cal is mt.TCMB:
                    calendar = self.history._typed_rows(user, {cal.first + k: d for k, d in typed.items()})
                else:
                    after = list(rows)
                    for k, d in typed.items():
                        after[k] = d
                    new = sorted({d for d in after if d})
                    calendar = mt.change(self, cal, rows, new, user)
                    calendar["typed_to"] = {k: (new.index(d) if d else None) for k, d in typed.items()}
            except ServiceError as exc:
                errors.append("toplantı takvimi: %s" % exc)
                continue
            typed_n = len(typed)
            # values typed in the same write as a date go with that date's meeting; the other rows' with the meeting
            # their row showed (it may have moved) - the dates were written first
            slot_to, typed_to = calendar.pop("slot_to", {}), calendar.pop("typed_to", {})
            user_vals, user_clear, shared_vals, shared_clear = (
                self._follow_meetings(book, cal, slot_to, typed_to, x) for x in (user_vals, user_clear, shared_vals, shared_clear))
        # ISINs of a list of bonds written: what each row held goes with its bond first (rowkeys.py) - the values written
        # with them land on the rows as typed
        trading = self._trading_before(book, list(shared_vals) + list(shared_clear))
        row_values = self.rowkeys.before_write(user, book, shared_vals, shared_clear, user_vals, user_clear)
        if shared_clear:
            book.engine.clear_inputs(shared_clear)
            self.store.clear_shared_inputs(book.id, [book.ref(si, rc) for si, rc in shared_clear])
        ret_hid = None
        if shared_vals:
            # the RET curve as it was: the history says what an upload changed, tenor by tenor
            ret_before = self._ret_rows(book) if any(book.inputs[k].group == "ret" for k in shared_vals) else None
            book.engine.set_inputs(shared_vals)
            self.store.set_shared_inputs(book.id, {book.ref(si, rc): _to_json(v) for (si, rc), v in shared_vals.items()}, user,
                                         {book.ref(si, rc): e.text for (si, rc), e in shared_forms.items()})
            if ret_before is not None:
                after = self._ret_rows(book)
                ret_hid = self.store.add_ret_history(user, after, {"changes": ret_changes(ret_before, after)})
        if shared_vals or shared_clear:
            self.formulas.wrote(book, "", shared_vals, shared_clear, shared_forms)
            self._follow_try_holidays(book, list(shared_vals) + shared_clear)
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
        res: Dict[str, Any] = {"applied": len(shared_vals) + sum(1 for c in shared_clear if c not in quiet) + len(user_vals)
                               + sum(1 for c in user_clear if c not in quiet) + typed_n + tw_blank,
                               "errors": errors}
        if typed_dates:
            res["shortcuts"] = typed_dates               # what was typed as a shortcut, for the cell's tooltip
        if calendar:
            res["calendar"] = calendar
            if calendar.get("note"):
                res["note"] = calendar["note"]         # (what the change did, as the page's toast says it)
        if row_values:
            res["row_values"] = row_values
        if trading is not None:
            self._trading_after(trading, res)
        if lenient:
            res["skipped"] = skipped
        if ret_hid is not None:
            res["ret_history"] = ret_hid                 # (the RET's history entry this write made)
        return res

    @staticmethod
    def _typed_dates(cal, rows: List[Optional[str]], typed: Dict[int, Optional[str]], errors: List[str]) -> Dict[int, Optional[str]]:
        """The dates typed into a meeting list (``{slot: ISO date or None}``) that may change it - the others refused
        with the reason, in ``errors``.  A date twice in the list is refused (two rows, one meeting: the second would
        take the first's place).  A TCMB date blanked over a meeting is refused (Delete over a selection that holds
        dates, a pasted block with empty dates): a meeting leaves the list on Ayarlar → Toplantı takvimi.  An FOMC
        date may be blanked - the USD · FOMC page is where that list is edited; what was typed for the meeting is set
        aside, as for any meeting that leaves a list."""
        from . import meetings as mt
        out = {k: d for k, d in typed.items() if d is not None or rows[k]}       # (blank over an empty row: nothing)
        if cal is mt.TCMB:
            blank = sorted(k for k, d in out.items() if d is None)
            if blank:
                errors.append("toplantı tarihi silinmez (%s): bir toplantıyı listeden çıkarmak için %s'nde ✕ kullanın - "
                              "toplantıya yazılmış değerler kenara alınır, tarih geri eklenirse geri gelir"
                              % (", ".join("%s!%s%d" % (cal.sheet, cal.key, cal.first + k) for k in blank), cal.where))
                for k in blank:
                    del out[k]
        after = list(rows)
        for k, d in out.items():
            after[k] = d
        for k in sorted(out):
            d = out[k]
            if d is None:
                continue
            other = [m for m, x in enumerate(after) if x == d and m != k]
            if other:
                errors.append("%s!%s%d: %s listede zaten var (%s%d) - aynı günde iki toplantı olmaz"
                              % (cal.sheet, cal.key, cal.first + k, mt.tr_day(d), cal.key, cal.first + other[0]))
                after[k] = rows[k]
                del out[k]
        return {k: d for k, d in out.items() if d != rows[k]}

    @staticmethod
    def _follow_meetings(book: Book, cal, slot_to: Dict[int, Optional[int]], typed_to: Dict[int, Optional[int]], cells):
        """Cells of a write that are in a meeting's row, where they are after the dates of the same write moved the list
        (a dict's keys or a list): a row whose date was typed - that date's row; any other row - its meeting's row now.
        A cell whose meeting left the list (or a row without a meeting that one came to) is left out."""
        from . import meetings as mt
        from .xl.tokenizer import col_to_index

        def where(key: Tuple[int, int]) -> Optional[Tuple[int, int]]:
            hit = mt.place(book, key[0], key[1])
            if hit is None or hit[0] is not cal or hit[1].kind == mt.KEY:
                return key
            b, k, col = hit[1], hit[2], hit[3]
            to = typed_to[k] if k in typed_to else slot_to.get(k, k)
            if to is None:
                return None
            return key[0], (b.first + to) * COLS + col_to_index(col)

        if isinstance(cells, dict):
            out: Dict[Tuple[int, int], Any] = {}
            for key, v in cells.items():
                to = where(key)
                if to is not None:
                    out[to] = v
            return out
        return [to for to in (where(key) for key in cells) if to is not None]

    @staticmethod
    def _meeting_date_cell(book: Book, si: int, rc: int) -> bool:
        """A meeting date of a meeting list (TCMB: OIS_MAIN!P10:P89, Fed: SOFR_FOMC!B74:B83 - meetings.py): it changes
        through the calendar only, which moves what was typed per meeting along with it."""
        from . import meetings as mt
        return mt.key_of(book, si, rc) is not None

    @staticmethod
    def _moved_by_calendar(book: Book, si: int, rc: int) -> bool:
        """A cell whose value goes with its meeting when a meeting list changes (meetings.py: the date, what is typed per
        meeting, the desk's label) - for the desk and for every user; a reference to it follows it too."""
        from . import meetings as mt
        return mt.follows(book, si, rc)

    def _holiday_cell(self, book: Book, si: int, rc: int) -> bool:
        """A day or its name in a holiday list (``HOLIDAY_LISTS``): a save of the list (Ayarlar → Tatiller) writes all of
        it again in date order - what a cell holds goes to whichever row its day sorts to."""
        sheet = book.model.sheets[si].name
        r, c = divmod(rc, COLS)
        col = index_to_col(c)
        return any(bid == book.id and name == sheet and r1 <= r <= r2 and col in (dcol, ncol)
                   for lists in self.HOLIDAY_LISTS.values() for bid, name, r1, r2, dcol, ncol in lists)

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
                if key in book.inputs or key in book.twoway or allow_adhoc:     # (a two-way member: into its store)
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
        self._follow_trading(user, res)            # (the trading list back to the file's: the ASW list follows)
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
            cells = self.twoway.widen(book, cells)          # (a two-way table's cell: its row back to its default)
        n = 0
        res: Dict[str, Any] = {}
        if shared:
            from . import meetings as mt
            cal = next((c for c in (mt.key_of(book, si, rc) for si, rc in cells) if c is not None), None)
            if cal is not None:
                # the file's dates are those of the day it was saved: put back over the list, the steps would no longer
                # be those of their meetings
                raise ServiceError("toplantı tarihleri dosyadaki değere döndürülmez – listeyi %s üzerinden düzeltin "
                                   "(toplantıya yazılanlar toplantısıyla taşınır)" % cal.where)
            keep = [c for c in cells if c in book.inputs and book.inputs[c].scope == "shared"]
            trading = self._trading_before(book, keep)
            rows = self.rowkeys.before_write(user, book, {}, keep, {}, [])     # (a list of bonds back to the file's)
            book.engine.clear_inputs(keep)
            self.store.clear_shared_inputs(book.id, [book.ref(si, rc) for si, rc in keep])
            self.formulas.cleared("", book, keep)        # (a formula there goes with its value)
            self._follow_try_holidays(book, keep)
            n = len(keep)
            if trading is not None:
                self._trading_after(trading, res)        # (the trading list back to the file's: what entered, what left)
        else:
            rows = self.rowkeys.before_write(user, book, {}, [], {}, cells if refs else list(self._overlay(user, book)))
            # (ÇAPRAZ FORWARD's currency back to its default, another one: its typed forwards go too - not counted)
            gone = self._cross_typed_forwards(user, book, None, {}, cells) if refs else []
            ov = dict(self._overlay(user, book))
            targets = cells if refs else list(ov.keys())
            for k in targets:
                if k in ov:
                    del ov[k]
                    n += 1
            for k in gone:
                ov.pop(k, None)
            targets = targets + [k for k in gone if k not in targets]
            self._overlays[(user, book.id)] = ov
            book.engine.set_user_inputs(user, ov)
            if refs:
                self.store.clear_user_inputs(user, book.id, [book.ref(si, rc) for si, rc in targets])
            else:
                self.store.clear_user_inputs(user, book.id)
            self.formulas.cleared(user, book, targets if refs else None)
            self._note_private(user)
        res["reset"] = n
        if rows:
            res["row_values"] = rows
        return res

    # ================================================================== temporary copies of a table (copies.py)
    def copies_of(self, user: Optional[str]) -> Dict[str, Any]:
        """The user's temporary copies: ``{"copies": [{"id", "view", "panel", "pid", "n", "at", "values"}], "max_per_table",
        "max_per_user"}``."""
        from .copies import MAX_PER_TABLE, MAX_PER_USER
        return {"copies": [cp.info() for cp in self.copies.items(self.require_user(user))],
                "max_per_table": MAX_PER_TABLE, "max_per_user": MAX_PER_USER}

    def copy_action(self, user: Optional[str], what: str, data: Any, lang: Optional[str] = None) -> Dict[str, Any]:
        """A temporary copy opened (``open`` {view, panel}), closed (``close`` {copy}), typed into (``inputs`` {copy,
        items, lenient?} - as ``set_inputs``), or its own values taken away (``reset`` {copy, refs?})."""
        user = self.require_user(user)
        if not isinstance(data, dict):
            raise ServiceError("geçersiz istek")
        cp = self.copies
        if what == "open":
            res = self.et.call_at(EngineThread.WRITE, cp.open, user, data.get("view"), data.get("panel"))
        elif what == "close":
            res = self.et.call_at(EngineThread.WRITE, cp.close, user, data.get("copy"))
        elif what == "inputs":
            res = self.et.call_at(EngineThread.WRITE, cp.set_inputs, user, data.get("copy"), data.get("items"),
                                  lang or self.settings.locale, _flag(data.get("lenient")))
        elif what == "reset":
            res = self.et.call_at(EngineThread.WRITE, cp.reset, user, data.get("copy"), data.get("refs"))
        else:
            raise ServiceError("bilinmeyen işlem: %s" % str(what)[:40], 404)
        self.bump()
        res["gen"] = self.gen
        return res

    def my_inputs(self, user: str) -> Dict[str, Any]:
        """The user's personal inputs: ``{"inputs": [{"book", "ref", "value", "label", "formula"?, "store"?, "at",
        "pages", "market"?, "old"?, "hand"?}], "desk": [...], "today"}`` - an input typed as a formula with its text and
        the value it has now; ``at`` when it was typed (the store's time); ``pages`` the pages (and tables) that show it;
        ``market`` what it is when it is a market level (tto/myinputs.py) and ``old`` when such a level was typed before
        today (the desk, 28.11.2026: "Dünden kalan yazılmış değerler işaretli"); ``hand`` a value typed over a formula
        ("Elle değer").  ``desk``: the desk's own market levels (shared inputs - the manual spot) the same way, with who
        typed them (``by``)."""
        from . import myinputs as mi
        user = self.require_user(user)
        out = []
        formulas = self.store.user_formulas(user)
        times = self.store.input_times(user)
        today = _dt.date.today().isoformat()
        index = self._page_index()
        skip = self._hidden_pages(user)
        for (bid, ref), val in sorted(self.store.user_inputs(user).items()):
            book = self.books.get(bid)
            label = ""
            at = (times.get((bid, ref)) or ("", None))[0]
            item: Dict[str, Any] = {"book": bid, "ref": ref, "value": val, "label": label, "at": at}
            if book is not None:
                try:
                    cell = book.cell(ref)
                    if cell in self._retired_cells(book):
                        continue                       # an input that moved: dropped when the values are loaded
                    d = book.inputs.get(cell)
                    item["label"] = d.label if d else ""
                    h = book.twoway.get(cell)
                    if h is not None and h.store:
                        item["ref"] = book.ref(*h.member_cell)       # (a two-way table's: the cell it was typed into)
                        item["store"] = ref
                    if (bid, ref) in formulas:
                        item["formula"] = formulas[(bid, ref)]
                        now = self._overlays.get((user, bid), {}).get(cell, _NOT_SET)
                        if now is not _NOT_SET:
                            item["value"] = _to_json(now)
                    si, rc = cell
                    if d is not None and d.group == "adhoc" and rc in book.model.sheets[si].fml:
                        item["hand"] = True             # ("Elle değer": typed over the workbook's formula)
                    self._mark_market(mi, book, item, d, cell, today)
                except (KeyError, ValueError):
                    pass
            item["pages"] = index.pages(bid, item["ref"], skip)
            out.append(item)
        desk = []
        shared = self.store.shared_inputs()
        for (bid, ref), (at, by) in sorted(self.store.input_times(None).items()):
            book = self.books.get(bid)
            val = shared.get((bid, ref))
            if book is None or val is None or mi.market_label(bid, ref) is None:
                continue
            try:
                cell = book.cell(ref)
            except (KeyError, ValueError):
                continue
            d = book.inputs.get(cell)
            if d is None or d.scope != "shared":
                continue
            item = {"book": bid, "ref": ref, "value": val, "label": d.label, "at": at or "", "by": by, "shared": True}
            self._mark_market(mi, book, item, d, cell, today)
            if item.get("market"):
                item["pages"] = index.pages(bid, ref, skip)
                desk.append(item)
        return {"inputs": out, "desk": desk, "today": today}

    def _mark_market(self, mi: Any, book: Book, item: Dict[str, Any], d: Any, cell: Tuple[int, int], today: str) -> None:
        """``market`` (what it is) and ``old`` (typed before ``today``) on a typed value that is a market level - a
        number, not a setting (tto/myinputs.py); one typed as a formula reads its cells live: never old."""
        label = mi.market_label(book.id, item["ref"])
        if label is None:
            return
        si, rc = cell
        fmt = self.renderers[book.id].format_of(si, rc) if book.id in self.renderers else None
        if not mi.is_level(item["value"], d.kind if d is not None else None, fmt):
            return
        item["market"] = label
        item["old"] = bool(item.get("at")) and item["at"][:10] < today and not item.get("formula")

    def _page_index(self) -> Any:
        """Which pages show a cell (tto/myinputs.py) - made once: the views do not change while the dashboard runs."""
        idx = getattr(self, "_pages_of_cells", None)
        if idx is None:
            from .myinputs import PageIndex
            idx = self._pages_of_cells = PageIndex(self.views)
        return idx

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

        def load() -> None:
            # in the engine's queue of writes, as an input written is: a write sent before the load is applied before
            # it (the load wins), one sent after it after - never a write still waiting in the queue landing over the
            # loaded inputs
            self.store.replace_user_inputs(user, values, formulas)  # (its formulas evaluated again over what is there now)
            self._reload_user(user)
            # (the user's own list of bonds is the scenario's, with its rows' values: nothing moves - rowkeys.py)
            self.rowkeys.loaded(user)

        self.et.call_at(EngineThread.WRITE, load)
        self.bump()
        return {"loaded": name, "cells": len(values), "gen": self.gen}

    def delete_scenario(self, user: str, name: str) -> Dict[str, Any]:
        user = self.require_user(user)
        if not self.store.delete_scenario(user, name):
            raise ServiceError("senaryo bulunamadı: %s" % name, 404)
        return {"deleted": name}

    def _reload_user(self, user: str) -> None:
        if self.formulas is not None:
            self.formulas.reread()                      # (a scenario's formula that may not stand goes before it is listed)
        for book in self.books.values():
            self._overlays.pop((user, book.id), None)
            ov = self._overlay(user, book)
            book.engine.set_user_inputs(user, ov)
        self._note_private(user)

    def _note_private(self, user: Optional[str] = None) -> None:
        """Whether a user has inputs of their own (``None``: every user, read again) - the pages they share follow it.
        Their kept pages and header are made again: what they typed shows at once."""
        copies = getattr(self, "copies", None)
        if user is None:
            users = set(self.store.users_with_inputs())
            if copies is not None:
                users |= copies.users()                # (a page that holds a user's copies is theirs)
            with self._render_lock:
                self._private_users = users
                self._renders.clear()
            return
        mine = bool(self.store.user_inputs(user)) or (copies is not None and copies.has(user))
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
    #: the columns a table hides until its user chooses otherwise ("Sütunlar" shows them, and that choice is kept):
    #: DİBS RV's own FX swap columns (BF:BJ, on the offshore ICAP curve of the Forward sheet) - the desk reads a bond's
    #: FX swap side on DİBS ASW's FX swap implied curve (EK_FX: DİBS RV · Genel's "FX swap ASW", DİBS Trading, the card),
    #: and the TRY workbook cannot work it out itself: it holds the quotes (Forward!AO6:AO26, VİOP!C58:C69), not DİBS
    #: ASW's curve made of them nor its source order (ICPL, then BGN; MID first) - and its two helper columns (27.11.2026,
    #: "Düzen": the widest table, only helpers): Q "İşlemiş (valör)", the accrued interest Kirli (valör) − Kullanılan temiz
    #: beside it, and BE "Durum", where the bond's cash flows were built (BBG CF / takvim / iskontolu) or why they were not.
    #: USD · FOMC's helper columns (the desk's layout review, 27.11.2026: "Hepsini yap"): the FOMC table's day counts and ln DFs its İma O/N % is worked out from
    #: (Başl. gün, Bitiş gün, ln DF başl., ln DF bitiş) and the OIS quotes' helpers (Kullan, Ay, Hafta, ln DF, SOFR / FF
    #: ticker roots) - never a rate, a step or a quote the desk reads
    DEFAULT_HIDDEN_COLUMNS: Dict[str, Tuple[str, ...]] = {
        "v/dibs/B3": ("Q", "BE", "BF", "BG", "BH", "BI", "BJ"),
        "v/usd/fomc": ("F", "G", "I", "J"),
        "v/usd/crv": ("G", "H", "I", "M", "S", "T"),
    }

    def columns(self, user: Optional[str]) -> Dict[str, Any]:
        """The columns this user hid, table by table: ``{"tables": {"v/dibs/B5": ["B", "K"], ...}}`` - and, when they
        put the columns of a table in an order of their own, ``"order": {"v/dibs/B5": ["C", "A", "B", ...]}``; the
        tables they never chose for with what those hide by default (``DEFAULT_HIDDEN_COLUMNS``): ``"defaults"``."""
        key = self.require_user(user)
        tables = self.store.get("cols." + key) or {}
        out: Dict[str, Any] = {"tables": tables}
        defaults = {t: list(c) for t, c in self.DEFAULT_HIDDEN_COLUMNS.items() if t not in tables}
        if defaults:
            out["defaults"] = defaults
        order = self.store.get("colorder." + key) or {}
        if order:
            out["order"] = order
        return out

    #: the columns of one table a user may name in an order of their own
    MAX_ORDER_COLUMNS = 400
    #: the 19 quant signal lists share one column choice (``quant/signals``: quantbase.js SIGNALS_TABLE - Sinyaller's list, its
    #: box, every analysis page's; Düzen, 27.11.2026, the desk: "Hepsini yap"): until a user chooses, the secondary statistics
    #: are hidden - the asset class (the trade names it), the half-life (the holding beside it), the regime, the families
    #: agreeing and the gates (the card shows all four; a held line's reason stays in "Bileşik / neden") -, never the trade,
    #: its levels, P&L, record or carry
    DEFAULT_HIDDEN_COLUMNS["quant/signals"] = ("Varlık", "Yarı ömür (g)", "Rejim", "Uyum", "Kapılar")

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
        """Hide these columns of one table from this user (an empty list shows every column again - kept as such for a
        table that hides some by default, ``DEFAULT_HIDDEN_COLUMNS``)."""
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
            if cols or table in self.DEFAULT_HIDDEN_COLUMNS:
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
    #: launchpads, the side drawer, the favourite pages, the page the dashboard opens on, their own menu and the
    #: compact look - kept with the account (``layout.<user>``; see layout.py): any computer they sign in from shows the
    #: same, an update keeps it
    MAX_LAYOUT_BYTES = 256 * 1024
    _layout_lock = threading.Lock()

    def layout(self, user: Optional[str]) -> Dict[str, Any]:
        """``{"launchpads": [{"name", "items": [...]}, ...], "drawer": [...], "favs": [...], "landing": "",
        "hidden_pages": [...], "compact": false, "rev": n}`` - and, while the desk has default favourites (an
        administrator sets them), ``desk_favs``: a user who never chose favourites of their own gets those as ``favs``
        (``favs_desk``: true)."""
        return self._desk_favs(lay.stored(self.store.get("layout." + self.require_user(user))))

    def _desk_favs(self, cur: Dict[str, Any]) -> Dict[str, Any]:
        """A layout as the browser gets it: the desk's default favourites with it, in place of the user's own while they
        have none (the desk, 28.11.2026: "yöneticinin varsayılan favorileri"); whether the user's are their own is kept,
        not sent."""
        out = {k: v for k, v in cur.items() if k != "favs_own"}
        desk = lay.desk_favs(self.store.get(lay.DESK_KEY))
        if desk:
            out["desk_favs"] = desk
            if not cur.get("favs_own"):
                out["favs"] = desk
                out["favs_desk"] = True
        return out

    def set_layout(self, user: Optional[str], data: Any) -> Dict[str, Any]:
        """Replace the parts of this user's layout that ``data`` sends (``launchpads``, ``drawer``, ``favs``,
        ``landing``, ``hidden_pages``, ``compact``); the others stay.  Returns the whole layout as kept.
        ``desk_favs`` (administrators only): the desk's default favourites - the top bar of everybody who has no
        favourites of their own."""
        key = self.require_user(user)
        if isinstance(data, dict) and "desk_favs" in data:
            self.require_admin(user)
            try:
                favs = lay.favs(data["desk_favs"])
            except lay.LayoutError as exc:
                raise ServiceError(str(exc))
            self.store.put(lay.DESK_KEY, {"favs": favs, "by": key, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            data = {k: v for k, v in data.items() if k != "desk_favs"}
            if not data:
                return self.layout(user)
        with self._layout_lock:
            cur = lay.stored(self.store.get("layout." + key))
            try:
                new = lay.change(cur, data)
            except lay.LayoutError as exc:
                raise ServiceError(str(exc))
            self._put_layout(key, new)
        return self._desk_favs(new)

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
        from .copies import copy_pid
        # a temporary copy is its owner's: whoever imports the file gets the table itself in its place
        lp = dict(lp, items=[dict(it, panel=copy_pid(it["panel"])[0]) if it.get("type", "table") == "table"
                             and isinstance(it.get("panel"), str) and copy_pid(it["panel"]) else it for it in lp["items"]])
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
        return {"name": lp["name"], "layout": self._desk_favs(new)}

    # ================================================================== RET curve
    #: where the RET table's tenor labels are looked for (Forward!V): a tenor is found by its label, not by its row
    RET_LABEL_ROWS = (30, 60)

    def _ret_layout(self, book: Book) -> List[Tuple[str, int]]:
        """The RET tenors in order and the row of each (``[("ON", 33), ...]``): the row whose label in Forward!V is the
        tenor's - wherever the table's rows are; a label the column does not hold keeps its row of the shipped
        workbook.  The workbook's own constants only (no calculation: any thread)."""
        si = book.model.sheet_index["Forward"]
        consts = book.model.sheets[si].consts
        col = col_to_index("V")
        found: Dict[str, int] = {}
        for r in range(self.RET_LABEL_ROWS[0], self.RET_LABEL_ROWS[1] + 1):
            v = consts.get(r * COLS + col)
            if isinstance(v, str):
                lab = v.strip().upper()
                if lab in RET_TENORS and lab not in found:
                    found[lab] = r
        return [(t, found.get(t, RET_FIRST_ROW + i)) for i, t in enumerate(RET_TENORS)]

    def _ret_cells(self, book: Book) -> List[str]:
        return ["Forward!%s%d" % (col, r) for _, r in self._ret_layout(book) for col in ("W", "X")]

    def _ret_rows(self, book: Book) -> List[Dict[str, Any]]:
        calc = book.engine.shared
        si = book.model.sheet_index["Forward"]
        rows = []
        for tenor, r in self._ret_layout(book):
            rows.append({"tenor": tenor, "days": _to_json(calc.get(si, r, 21)), "bid": _to_json(calc.get(si, r, 23)),
                         "ask": _to_json(calc.get(si, r, 24))})
        return rows

    def ret(self) -> Dict[str, Any]:
        return self.et.call(self._ret)

    def _ret(self) -> Dict[str, Any]:
        book = self._book("tto")
        return {"rows": self._ret_rows(book), "meta": self.store.shared_meta("tto", self._ret_cells(book)), "gen": self.gen}

    def set_ret(self, user: str, rows: List[Dict[str, Any]], lang: Optional[str] = None) -> Dict[str, Any]:
        """rows: [{"tenor": "1M", "bid": "34,45", "ask": "34,65"}, ...] - percent or fraction, any separator."""
        user = self.require_user(user)
        items = []
        index = dict(self._ret_layout(self._book("tto")))
        for row in rows:
            t = str(row.get("tenor", "")).upper().strip().replace("O/N", "ON").replace("T/N", "TN").replace("12M", "1Y")
            if t not in index:
                raise ServiceError("bilinmeyen RET vadesi: %r" % row.get("tenor"))
            r = index[t]
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
        book = self.books.get("tto")
        if book is None:
            return None
        return self.store.shared_meta("tto", self._ret_cells(book))

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
        out.update(self._templates(user))              # what the entry form can be filled from (Şablonlar)
        if out["can_enter"]:
            self._blotter_copies(book, trades)         # "Benzerini gir" / "Ters işlem" of every trade listed
        loc = numfmt.get_locale(locale or self.settings.locale)
        if ranged:
            out["days"] = len({t["trade_date"] for t in trades})
        if date == today and not ranged:
            calc = book.engine.shared
            sheet_panels = self._blotter_panels(book, calc, trades, loc)
            out["sheet"] = sheet_panels
            # the day's archive: the summary tables as shown and the whole sheet as values (what the workbook's
            # end-of-day macro saved); written only when something changed
            snap = {"sheet": sheet_panels, "cells": self._blotter_cells(book, calc)}
            mark = hash(json.dumps(snap, ensure_ascii=False, sort_keys=True, default=str))
            if self._snapshot_mark.get(date) != mark:
                self.store.save_blotter_snapshot(date, snap)
                self._snapshot_mark = {date: mark}
            return out
        snap = None if ranged else self.store.blotter_snapshot(date)
        if not ranged:
            out["snapshot_at"] = snap.get("snapshot_at") if snap else None
        if snap:
            out["sheet"] = snap.get("sheet") or []     # a day gone by: its archive, as the tables were that day
        elif not trades:
            out["sheet"] = []
        else:
            # a period, or a day gone by with no archive: the same tables over the trades shown - the sheet's own
            # formulas with its lists filled with them, in a calculation of its own (the sheet itself keeps today's)
            left: Dict[str, int] = {}
            calc = self._blotter_layer(book, (date, date_to), bl.sheet_values(book, trades, left))
            out["sheet"] = self._blotter_panels(book, calc, trades, loc)
            out["sheet_scope"] = self._blotter_scope(date, date_to, ranged, trades, left)
        return out

    #: the summary tables of the last periods (and days gone by) asked for, each kept as a layer of the engine
    BLOTTER_LAYERS = 4

    def _blotter_layer(self, book, key: Tuple[str, str], overlay: Dict[Tuple[int, int], Any]) -> Calc:
        """The calculation of a period's summary tables: a layer of the engine over the shared one with the blotter
        lists filled with the period's trades (``overlay``) - kept, so a refresh evaluates only what changed (the
        market, a trade); the last :data:`BLOTTER_LAYERS` periods asked for are kept, an older one dropped."""
        eng = book.engine
        kept = self.__dict__.setdefault("_blotter_layers", [])
        name = ("", "blotter-tables") + tuple(key)
        if name in kept:
            kept.remove(name)
        kept.append(name)
        while len(kept) > self.BLOTTER_LAYERS:
            eng.drop_layer(kept.pop(0))
        return eng.layer(name, eng.shared, overlay)

    #: the workbook's own summary tables of the blotter sheet the page shows: id, title, range
    BLOTTER_TABLES = (("fwd", "Forward · vade kovaları (USD karşılığı, TL maliyeti, DV01)", "P1:W20"),
                      ("ois", "OIS · vade özeti (MPC işlemleri ana vadelere dağıtılmış)", "O22:W39"),
                      ("bond", "Bonds", "P41:V84"), ("cpt", "OIS — CPT x VADE (DV01 USD)", "P87:V349"))

    def _blotter_panels(self, book, calc, trades: List[Dict[str, Any]], loc) -> List[Dict[str, Any]]:
        """The blotter sheet's summary tables (:data:`BLOTTER_TABLES`) as ``calc`` has them - the shared calculation
        (today's trades: the sheet) or one with the lists filled with other trades - the forward buckets' DV01 beside."""
        R = self.renderers[book.id]
        panels = []
        for pid, title, rng in self.BLOTTER_TABLES:
            try:
                data = R.table(calc, bl.SHEET, rng, loc, None)
                _lift_title(data)
                if pid == "fwd":
                    _add_dv01_columns(data, bl.forward_dv01_buckets(book, calc, trades), loc)
                panels.append({"id": pid, "title": title, "range": rng, "data": data})
            except Exception as exc:  # noqa: BLE001
                panels.append({"id": pid, "title": title, "error": str(exc)[:200]})
        return panels

    @staticmethod
    def _blotter_scope(date: str, date_to: str, ranged: bool, trades: List[Dict[str, Any]], left: Dict[str, int]) -> str:
        """What the summary tables of a period (or of a day gone by without its archive) cover, said over them."""
        day = lambda iso: _dt.date.fromisoformat(iso).strftime("%d.%m.%Y")          # noqa: E731
        what = ("Aralık %s – %s: %d işlemin hepsi birlikte" % (day(date), day(date_to), len(trades)) if ranged else
                "%s: gün sonu arşivi yok - günün %d işlemiyle" % (day(date), len(trades)))
        text = what + ", Excel sayfasının kendi formülleriyle hesaplandı (sayfanın kendisi bugünün işlemlerini tutar); " \
                      "vade kovaları ve gün sayıları bugüne göre, işlemlerin kendi tutar, faiz ve DV01'leriyle"
        names = {"fwd": "forward", "ois": "OIS bacağı", "bond": "tahvil"}
        rows = {"fwd": bl.FWD_ROWS, "ois": bl.OIS_ROWS, "bond": bl.BOND_ROWS}
        over = ["%d %s" % (n, names[k]) for k, n in sorted(left.items()) if n]
        if over:
            text += ". Sayfanın listelerine sığmayan (en fazla %s): %s - maliyet tabloları hepsini sayar" % (
                " / ".join("%d %s" % (rows[k][1] - rows[k][0] + 1, names[k]) for k in ("fwd", "ois", "bond")), ", ".join(over))
        return text

    def _blotter_copies(self, book, trades: List[Dict[str, Any]]) -> None:
        """"Benzerini gir" / "Ters işlem" of each trade listed (``copy`` on a trade, an OIS package's first leg listed):
        what the entry form is filled with (:func:`blotter.copy_specs`) - from today's spot dates (the OIS spot
        ``OIS_MAIN!B2``, a pair's spot date) and the TRY holidays (Motor's), read as Fiyatlama reads them; nothing priced,
        nothing stored."""
        calc = book.engine.shared
        idx = book.model.sheet_index
        try:
            mk = pr.read(lambda sheet, r, c: calc.get(idx[sheet], r, c))
        except pr.PricingError:
            return
        spots: Dict[str, Optional[float]] = {"USDTRY": mk.fx_spot, "EURTRY": mk.eur_spot}

        def fx_spot(pair: str) -> Optional[float]:
            if pair not in spots:
                got = self._pair_spot(pair) if self._own_spot(pair) else mk.fx_spot
                spots[pair] = got if type(got) is float else None
            return spots[pair]

        cal = {"today": self.today_iso(), "ois_spot": mk.ois_spot, "holidays": mk.holidays["TRY"], "fx_spot": fx_spot}
        packages: Dict[str, List[Dict[str, Any]]] = {}
        for t in trades:
            if t.get("kind") == "ois" and t.get("package"):
                packages.setdefault(t["package"], []).append(t)
        seen = set()
        for t in trades:
            pkg = t.get("package") if t.get("kind") == "ois" else None
            if pkg in seen:
                continue
            if pkg:
                seen.add(pkg)
            t["copy"] = bl.copy_specs(sorted(packages[pkg], key=lambda x: x["id"]) if pkg else [t], cal)

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
        # the pair comes last: the columns before it are where they were when every forward was USDTRY; after it, what
        # was typed (a minor-currency entry: the TRY amount of a USDTRY forward - the trade is in USD all the same)
        table("Forward", lead + ["Saat", "Kullanıcı", "Yön", "Tutar (döviz)", "Valör", "Gün", "TRY faizi", "Forward", "TL tutarı",
                                 "Fiyatlama", "Karşı taraf", "Not", "O/N karşılığı", "DV01 (TL)", "DV01 ($)", "Parite", "Swap puanı",
                                 "Girilen tutar", "Girilen döviz"],
              [when(t) + [clock(t), who(t), "ALIŞ" if t["dir"] == "B" else "SATIŞ", t.get("amount"), t.get("value_date"), t.get("days"),
                          t.get("try_rate"), t.get("forward"), t.get("tl"), basis.get(t.get("basis"), t.get("basis") or ""),
                          t.get("cpt") or "", t.get("note") or "", t.get("on_rate"), t.get("dv01_tl"), t.get("dv01"),
                          t.get("pair") or "USDTRY", t.get("points")] + list(bl.entered_as(t)[1:]) for t in fw],
              lead_fmt + [None, None, None, INT, DATE, INT, P3, FX, AMT, None, None, None, P3, INT, INT, None, INT, AMT, None])
        seen = set()
        ois_rows = []
        for t in (x for x in trades if x["kind"] == "ois"):
            first = not t.get("package") or t["package"] not in seen
            if t.get("package"):
                seen.add(t["package"])
            ois_rows.append(when(t) + [clock(t), who(t), t.get("label") or "", role.get(t.get("role"), t.get("role") or ""),
                                       "RECEIVE" if t["dir"] == "S" else "PAY", t.get("tenor"), t.get("rate"), t.get("nominal"),
                                       _payer_plus(t),
                                       _vs_mid(t.get("cost_bp")) if first else None, _vs_mid(t.get("cost_usd")) if first else None,
                                       t.get("cpt") or "", t.get("note") or ""])
        table("OIS", lead + ["Saat", "Kullanıcı", "İşlem", "Bacak", "Yön", "Vade", "Oran", "Nominal (TL)", "DV01 ($)", "Mid'e göre (bp)",
                             "Mid'e göre ($)", "Karşı taraf", "Not"], ois_rows,
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

    def _pair_spot(self, code: str, calc=None) -> Optional[float]:
        """The spot date (serial) a value date of the pair counts from.  USDTRY's and EURTRY's are the Forward sheet's
        (I2, K2: from the desk's lists, or the date typed there - by the user whose ``calc`` it is; everybody's
        without one); EURUSD's is its own - two days after today that are business days of both USD and EUR, as K2
        counts EURTRY's, a TRY holiday not among them; any other pair counts from USDTRY's (one starting with EUR from
        EURTRY's), as before.  On the calculation thread."""
        from .fx import SPOT_LAG, add_week_days
        book = self.books.get("tto")
        if book is None:
            return None
        if self._own_spot(code):
            holidays = {serial_to_date(s) for s in self._calendar_serials(ex.pair_calendar(code))}
            day = add_week_days(serial_to_date(book.engine.clock.today()), SPOT_LAG.get(code, 2), holidays)
            return float(date_to_serial(day))
        si, rc = book.cell("Forward!K2" if code.startswith("EUR") else "Forward!I2")
        spot = (calc if calc is not None else book.engine.shared).get(si, *divmod(rc, COLS))
        if isinstance(spot, str):
            spot = parse_date(spot)
        return spot if type(spot) is float else None

    def _tenor_date(self, text: str, pair: str = "USDTRY") -> Optional[float]:
        """The value date of a date shortcut (tto/shortcuts.py: "2W", "3M", "1A", "ay sonu", "IMM", "+5" …) from the
        pair's spot date (:meth:`_pair_spot`): n weeks, or n months and then the next business day of the pair's
        calendar - the holidays of both its currencies (USDTRY: TRY and USD, EURTRY: TRY and EUR, EURUSD: USD and EUR;
        any other pair the TRY list, as before) - as the Forward sheet dates its tenors; ON / TN from today."""
        sc = shortcuts.date_shortcut(text)
        book = self.books.get("tto")
        if sc is None or book is None:
            return None
        try:
            code = bl.pair_of(pair)
        except bl.TradeError:
            code = "USDTRY"
        spot = self._pair_spot(code)
        if type(spot) is not float:
            return None
        holidays = {serial_to_date(s) for s in self._calendar_serials(ex.pair_calendar(code) or ("TRY",))}
        day = shortcuts.resolve(sc, serial_to_date(spot), serial_to_date(book.engine.clock.today()), holidays)
        return float(date_to_serial(day))

    #: the spot date a date typed into an input as a tenor counts from, when the page names no start of its own: the
    #: pair's (``_pair_spot``) - for the TRY money market (no pair, or "TRY") the workbook's SPOTDATE, T+1 on the TRY list
    TRY_SPOT = "OIS_MAIN!B2"

    def _date_context(self, book: Book, si: int, rc: int) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
        """How a date typed as a tenor counts in a cell, as its formulas say (tto/datecells.py): (the pair of the dates
        the cell is made of - a spot date: Forward!I2 USDTRY, K2 EURTRY, OIS_MAIN!B2 the TRY money market; an input the
        page definition gives a pair -, ``None`` when there is none or they do not agree; the date the workbook counts
        the cell's days from: ``O35 = O34-O33`` - the End counts from the Start; ``None``: from the spot)."""
        spots: Dict[Tuple[int, int], str] = {}
        if book.id == "tto":
            for ref, pair in [("Forward!" + s[0], s[1]) for s in ex.FX_SPOTS] + [(self.TRY_SPOT, "TRY")]:
                try:
                    spots[book.cell(ref)] = pair
                except (KeyError, ValueError):
                    continue

        def known(key: Tuple[int, int]) -> Optional[str]:
            if key in spots:
                return spots[key]
            d = book.inputs.get(key)
            return (str((d.tenor or {}).get("pair") or "").upper() or None) if d is not None else None

        if book.dates is None:
            book.dates = datecells.DateCells(book.model)
        return book.dates.context(si, rc, known, spots)

    def _shortcut_date(self, user: Optional[str], book: Book, si: int, rc: int, d, text: Any, calc,
                       pending: Dict[Tuple[int, int], Any]) -> Optional[float]:
        """The date (serial) a shortcut typed into a date input stands for (tto/shortcuts.py) - ``None`` when the text
        is no shortcut.  How it counts is the input's ``tenor`` in its page definition (tto/views/__init__.py):
        ``pair`` (the calendar and the spot convention: USDTRY T+1 on TRY + USD, EURTRY T+2 on TRY + EUR, EURUSD T+2 on
        USD + EUR, "TRY" - the default - T+1 on the TRY list), ``pair_col`` (the row's pair, in that column) and
        ``from`` (the cell's natural start: a cell, a column of the row, a row of the column) - else today's spot,
        as the user's own calculation has it (a spot date typed over is theirs).  What the page definition does not
        say the formulas do (:meth:`_date_context`): the pair of a cell without one, the start of a cell the page says
        nothing of.  A start typed in the same write (a pasted block) counts as typed (``pending``).  On the
        calculation thread."""
        sc = shortcuts.date_shortcut(text)
        tto = self.books.get("tto")
        if sc is None or tto is None:
            return None
        decl = dict(d.tenor or {})
        if not (decl.get("pair") or decl.get("pair_col")) or d.tenor is None:
            pair, start_at = self._date_context(book, si, rc)
            if pair and not (decl.get("pair") or decl.get("pair_col")):
                decl["pair"] = pair
            if start_at is not None and d.tenor is None:     # (a page definition without "from": from the spot)
                decl["from"] = start_at

        def place(spec: Any) -> Optional[Tuple[int, int]]:
            return self._date_place(book, si, rc, spec)

        def value(at: Tuple[int, int]) -> Any:
            if at in pending:
                return pending[at]
            return calc.get(at[0], *divmod(at[1], COLS))

        code = str(decl.get("pair") or "TRY").upper()
        if decl.get("pair_col"):
            at = place(decl["pair_col"])
            typed = value(at) if at is not None else None
            try:
                code = bl.pair_of(typed) if isinstance(typed, str) and typed.strip() else code
            except bl.TradeError:
                pass
        tcalc = self._calc(user, tto) if user else tto.engine.shared
        if code == "TRY":
            holidays = {serial_to_date(s) for s in self._calendar_serials(("TRY",))}
            si2, rc2 = tto.cell(self.TRY_SPOT)
            spot = tcalc.get(si2, *divmod(rc2, COLS))
        else:
            holidays = {serial_to_date(s) for s in self._calendar_serials(ex.pair_calendar(code) or ("TRY",))}
            spot = self._pair_spot(code, tcalc)
        today = serial_to_date(tto.engine.clock.today())
        start = None
        at = place(decl["from"]) if decl.get("from") else None
        if at is not None and at != (si, rc):
            got = value(at)
            if isinstance(got, str):
                got = parse_date(got)
            if type(got) is float and 20000 < got < 80000:
                start = serial_to_date(got)
        if start is None:
            if type(spot) is float and 20000 < spot < 80000:
                start = serial_to_date(spot)
            else:                                                 # (no spot date to read: one business day on)
                from .fx import add_week_days
                start = add_week_days(today, 1, holidays)
        return float(date_to_serial(shortcuts.resolve(sc, start, today, holidays)))

    @staticmethod
    def _date_place(book: Book, si: int, rc: int, spec: Any) -> Optional[Tuple[int, int]]:
        """The cell a date input's ``tenor`` names (tto/views/__init__.py): a cell (``"C167"``, ``"Forward!I2"``), a
        column of the same row (``"B"``), a row of the same column (``"40"``) - or the cell the formulas name
        (:meth:`_date_context`)."""
        if isinstance(spec, tuple):
            return spec
        spec = str(spec or "").strip()
        r, c = divmod(rc, COLS)
        if re.match(r"^[A-Z]{1,3}$", spec):                       # a column: the cell of this row
            return si, r * COLS + col_to_index(spec)
        if re.match(r"^\d+$", spec):                              # a row: the cell of this column
            return si, int(spec) * COLS + c
        try:
            return book.cell(spec if "!" in spec else "%s!%s" % (book.model.sheets[si].name, spec))
        except (KeyError, ValueError):
            return None

    def _typed_day_rule(self, book: Book, si: int, rc: int, d, calc,
                        pending: Dict[Tuple[int, int], Any]) -> Tuple[_dt.date, bool, Optional[_dt.date]]:
        """How a day typed without its year counts in a date input (tto/inputs.py ``day_month``, the desk 28.11.2026):
        (today - the workbooks' TODAY() -, whether the cell asks about the past - ``datecells.PAST`` -, the start of the
        period it ends - the cell its page definition's ``"from"`` or its formulas name (:meth:`_date_context`), as
        typed in the same write or as the user's calculation has it; ``None``: none, or not a date)."""
        today = serial_to_date(book.engine.clock.today())
        if (si, rc) in datecells.past_cells(book.id, book.model):
            return today, True, None
        spec = (d.tenor or {}).get("from") if d is not None else None
        if spec is None and (d is None or d.tenor is None):
            spec = self._date_context(book, si, rc)[1]
        at = self._date_place(book, si, rc, spec) if spec else None
        if at is None or at == (si, rc):
            return today, False, None
        got = pending[at] if at in pending else calc.get(at[0], *divmod(at[1], COLS))
        if isinstance(got, str):
            got = parse_date(got)
        return today, False, (serial_to_date(got) if type(got) is float and 20000 < got < 80000 else None)

    def quote_forward(self, user: Optional[str], payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        return self.et.call(self._quote_forward, user, payload, lang)

    def _typed_today(self) -> _dt.date:
        """The day a date typed without its year counts from (tto/inputs.py ``day_month``): the workbooks' TODAY()."""
        book = self.books.get("tto")
        return serial_to_date(book.engine.clock.today()) if book is not None else _dt.date.today()

    def _fwd_payload(self, payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        lang = lang or self.settings.locale
        p = dict(payload)
        vd = p.get("value_date")
        if isinstance(vd, str):
            d = parse_date(vd, self._typed_today())          # (a day without its year: the next one - "26/12")
            if d is not None and yearless(vd):
                p["value_date_typed"] = " ".join(vd.split())  # (the form says what it became: "26/12 → 26.12.2026")
            if d is None:
                # "3M", "1A", "2H", "ay sonu", "IMM", "+5": from the pair's spot, on its calendar
                d = self._tenor_date(vd, str(p.get("pair") or "USDTRY"))
                if d is not None:
                    p["value_date_typed"] = " ".join(vd.split())
            if d is None:
                raise ServiceError("valör tarihi anlaşılamadı: %r (örn. 15.12.2026, 3M, 1A, ay sonu, IMM ya da +5)" % vd)
            p["value_date"] = d
        elif isinstance(vd, (int, float)):
            p["value_date"] = float(vd)
        amt = p.get("amount")
        if isinstance(amt, str):
            n = parse_amount(amt, lang)
            p["amount"] = n
        elif isinstance(amt, (int, float)):
            p["amount"] = float(amt)
        # the amount in the pair's second currency (TRY of USDTRY): a minor-currency entry
        qa = p.get("quote_amount")
        if isinstance(qa, str):
            p["quote_amount"] = parse_amount(qa, lang)
            if p["quote_amount"] is None and qa.strip():
                raise ServiceError("karşı tutar anlaşılamadı: %r (örn. 500m ya da 500.000.000)" % qa)
        elif isinstance(qa, bool) or not isinstance(qa, (int, float)):
            p["quote_amount"] = None
        else:
            p["quote_amount"] = float(qa)
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
        ov = self.interp.boot_overlay(user_key(user), book) if user else {}      # (the desk's records: on Bootstrap)
        try:
            q = bl.price_forward(book, ov, p["value_date"], str(p.get("basis", "RET_MID")).upper(),
                                 p.get("manual") if type(p.get("manual")) is float else None, p["pair"],
                                 p.get("spot") if type(p.get("spot")) is float else None, p["spot_date"])
        except bl.TradeError as exc:
            raise ServiceError(str(exc))
        try:
            typed = bl.typed_amount(p)
        except bl.TradeError:
            typed = None                          # (still being typed: the risk per 1 mn until it is an amount)
        direction = "S" if str(p.get("dir", "B")).upper() == "S" else "B"
        amount = None
        if typed is not None:
            # the side typed stays as it is, the other follows from this forward (a rate typed again moves only that one)
            amount, q["tl"] = bl.forward_amounts(typed, q["forward"], q["base"])
            q["amount"] = amount
            q["typed"], q["typed_amount"] = typed
        size = amount if type(amount) is float and amount > 0 else 1e6           # no amount yet: per 1 mn of the currency
        q["dv01"] = bl.forward_dv01(direction, size, q["forward"], q["days"], q.get("usdtry"), q.get("df_try"), q.get("df_usd"),
                                    q["try_rate"] if q["quote"] == "TRY" else None, q.get("usd_rate"))
        q["dv01"]["amount"] = size
        q["dv01"]["dir"] = direction
        q["value_date_iso"] = serial_to_date(q["value_date"]).isoformat()
        if p.get("value_date_typed"):
            q["value_date_typed"] = p["value_date_typed"]          # (typed as a shortcut: the form says what it became)
        return q

    def add_forward(self, user: str, payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        user = self.require_user(user)
        res = self.et.call_at(EngineThread.WRITE, self._add_forward, user, payload, lang)
        self.bump()
        return res

    def _add_forward(self, user, payload, lang=None) -> Dict[str, Any]:
        book = self._book("tto")
        try:
            rec = bl.forward_trade(book, self.interp.boot_overlay(user, book), self._fwd_payload(payload, lang))
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
        today = self._typed_today()
        for k in ("start", "end"):
            v = p.get(k)
            if isinstance(v, str):
                # a day without its year: the next one - an end from its start on ("26/12", the desk 28.11.2026)
                start = p.get("start") if k == "end" and type(p.get("start")) is float else None
                p[k] = parse_date(v, today, after=start)
                if p[k] is None and v.strip():
                    raise ServiceError("tarih anlaşılamadı: %r" % v)
            elif isinstance(v, bool) or not isinstance(v, (int, float)):
                p[k] = None
            else:
                p[k] = float(v)
        for k, at in (("start_months", "start_date"), ("end_months", "end_date")):
            # a FRA between dates of its own ("Ters işlem" of a day gone by's FRA): an end typed as a date, dd.mm.yyyy
            day = bl.tenor_date_of(p.get(k)) if isinstance(p.get(k), str) else None
            if day is not None:
                p[k], p[at] = None, day
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
        """The TRY OIS curve as the user sees it (``user``: a user key, or nobody) on Bootstrap whatever their curve setting
        - Günlük İşlemler prices and keeps the desk's records on the curve the desk marks with (interp.py) - and its PPK
        step twin the one kept for that calculation (:meth:`_try_curves`)."""
        calc = self.interp.boot_view(user, book)
        return bl.OisMarket(book, calc, self.interp.boot_overlay(user, book) if user else None,
                            curves=lambda: self._try_curves(book, calc))

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
        q, recs, package = self._ois_records(user, payload, lang)
        ids = self.store.add_trades(self.today_iso(), "ois", recs, user, package)     # every leg, or none
        self._sync_blotter()
        q["ids"] = ids
        return q

    def _ois_records(self, user, payload, lang=None) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[str]]:
        """An OIS trade as the form sends it, priced and checked: (its quote, the records of its legs, their package)."""
        book = self._book("tto")
        p = self._ois_payload(payload, lang)
        try:
            q = bl.ois_legs(self._ois_curve(user, book), p)
        except bl.TradeError as exc:
            raise ServiceError(str(exc))
        package = uuid.uuid4().hex[:12] if len(q["legs"]) > 1 else None
        sized = self._ois_sized(p)              # (kept: what an edit of a spread / fly sized by DV01 starts from)
        recs = []
        for lg in q["legs"]:
            rec = {"dir": lg["dir"], "tenor": lg["tenor"], "rate": lg["rate"], "dv01": lg["dv01"],
                   "nominal": lg["nominal"], "cpt": lg["cpt"], "role": lg["role"], "strategy": q["strategy"],
                   "label": q["label"], "level": q["level"], "side": q["side"],
                   "cost_bp": q["info"].get("cost_bp"), "cost_usd": q["info"].get("cost_usd"),
                   "market": q["info"].get("market"), "note": str(payload.get("note") or "").strip()[:200]}
            if lg.get("mpc"):
                rec["mpc"] = lg["mpc"]
            rec["size_mode"], rec["size_typed"] = sized
            recs.append(rec)
        return q, recs, package

    @staticmethod
    def _ois_sized(p: Dict[str, Any]) -> Tuple[str, Optional[float]]:
        """The size of an OIS trade as typed, read as ois_legs reads it: ("dv01", $/bp), else ("nominal", TL), else
        ("dv01", None) - the sheet's DV01."""
        dv01, nominal = p.get("dv01"), p.get("nominal")
        return ("dv01", dv01) if type(dv01) is float and dv01 > 0 else \
            ("nominal", nominal) if type(nominal) is float and nominal > 0 else ("dv01", None)

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
        calc = self.interp.boot_view(user_key(user) if user else None, book)       # (a record of the desk's: Bootstrap)
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
        rec = self._bond_record(user, payload, lang)
        tid = self.store.add_trade(self.today_iso(), "bond", rec, user)
        self.et.call_at(EngineThread.WRITE, self._sync_blotter)
        self.bump()
        rec["id"] = tid
        return rec

    def _bond_checked(self, payload: Dict[str, Any], lang: Optional[str]) -> Tuple[str, float, float]:
        """A bond trade as the form sends it, checked: (instrument, amount - + bought, − sold -, price)."""
        inst, amount, price = self._bond_payload(payload, lang)
        if not inst:
            raise ServiceError("enstrüman gerekli")
        if amount is None or amount == 0:
            raise ServiceError("tutar gerekli (+ alış / − satış)")
        if price is None or price <= 0:
            raise ServiceError("fiyat gerekli")
        return inst, amount, price

    def _bond_record(self, user: str, payload: Dict[str, Any], lang: Optional[str]) -> Dict[str, Any]:
        """A bond trade as the form sends it, checked, with its DV01: the record to keep."""
        inst, amount, price = self._bond_checked(payload, lang)
        rec = {"instrument": inst, "amount": amount, "price": price, "note": str(payload.get("note") or "").strip()[:200]}
        risk = self.et.call(self._bond_risk, user, inst, amount)           # (in place when on the calculation thread)
        rec.update({"dv01_tl": risk["dv01_tl"], "dv01": risk["dv01"],
                    "name": (risk["info"] or {}).get("name") if risk["known"] else None})
        return rec

    # ------------------------------------------------------------------ the entry form's templates ("Şablonlar")
    #: templates a user may keep, and the desk
    TEMPLATES_MAX = 100

    def trade_templates(self, user: Optional[str]) -> Dict[str, Any]:
        """The templates the user fills the entry form from: their own first, then the desk's (an administrator's)."""
        return self._templates(self.require_user(user))

    def _templates(self, user: Optional[str]) -> Dict[str, Any]:
        admin = self.desk.is_admin(user)
        names = {u["name"]: u["display"] for u in self.store.users()}
        rows = sorted(self.store.trade_templates(user), key=lambda r: (r["owner"] is None, entry.fold(r["name"]), r["id"]))
        return {"can_publish": admin,
                "templates": [{"id": r["id"], "name": r["name"], "kind": r["kind"], "spec": r["spec"], "shared": r["owner"] is None,
                               "by": names.get(r["created_by"], r["created_by"]), "updated_at": r["updated_at"],
                               "can_edit": r["owner"] is not None or admin} for r in rows]}

    def _template_to_change(self, user: str, tid: Any, admin: bool) -> Dict[str, Any]:
        """A template the user may change: their own; the desk's when they are an administrator."""
        try:
            row = self.store.trade_template(int(tid))
        except (TypeError, ValueError):
            row = None
        if row is None or row["owner"] not in (None, user):
            raise ServiceError("şablon bulunamadı", 404)
        if row["owner"] is None and not admin:
            raise ServiceError("masa şablonunu yalnızca bir yönetici değiştirebilir", 403)
        return row

    def save_trade_template(self, user: Optional[str], name: Any, kind: Any, spec: Any, shared: Any = False,
                            tid: Any = None) -> Dict[str, Any]:
        """A template kept (``tid`` None) or changed: its name, product and spec (:func:`entry.clean_spec`) - one's own,
        or the desk's (``shared``: an administrator's to publish, for everyone to fill the form from).  ``None`` for
        any of ``name`` / ``kind`` / ``spec`` / ``shared`` of a template changed keeps what it had (a rename)."""
        user = self.require_user(user)
        admin = self.desk.is_admin(user)
        row = self._template_to_change(user, tid, admin) if tid is not None else None
        if row is not None:
            name = row["name"] if name is None else name
            kind = row["kind"] if kind is None else kind
            spec = row["spec"] if spec is None else spec
            shared = (row["owner"] is None) if shared is None else shared
        name = " ".join(str(name or "").split())
        if not name:
            raise ServiceError("şablon adı gerekli")
        if len(name) > 60:
            raise ServiceError("şablon adı en fazla 60 karakter olabilir")
        try:
            spec = entry.clean_spec(str(kind or ""), spec)
        except entry.EntryError as exc:
            raise ServiceError(str(exc))
        owner = None if _flag(shared) else user
        if owner is None and not admin:
            raise ServiceError("masa şablonunu yalnızca bir yönetici yayımlayabilir", 403)
        with self.store.transaction():                     # the name looked up and the row written in one go
            mine = [r for r in self.store.trade_templates(user) if r["owner"] == owner and (row is None or r["id"] != row["id"])]
            twin = [r for r in mine if entry.fold(r["name"]) == entry.fold(name)]
            if twin:
                raise ServiceError("bu adla bir şablon var: %s" % twin[0]["name"], 409)
            if row is None:
                if len(mine) >= self.TEMPLATES_MAX:
                    raise ServiceError("en fazla %d şablon tutulur: önce birini silin" % self.TEMPLATES_MAX)
                saved = self.store.add_trade_template(owner, name, spec["kind"], spec, user)
            else:
                self.store.update_trade_template(row["id"], user, name=name, kind=spec["kind"], spec=spec, owner=owner)
                saved = row["id"]
        if owner is None or (row is not None and row["owner"] is None):
            self.bump()                                    # the desk's: on everyone's page at once
        return dict(self._templates(user), saved=saved)

    def delete_trade_template(self, user: Optional[str], tid: Any) -> Dict[str, Any]:
        user = self.require_user(user)
        row = self._template_to_change(user, tid, self.desk.is_admin(user))
        self.store.delete_trade_template(row["id"])
        if row["owner"] is None:
            self.bump()
        return dict(self._templates(user), deleted=row["id"])

    # ------------------------------------------------------------------ rows pasted from Excel ("Excel'den yapıştır")
    def bulk_preview(self, user: Optional[str], kind: Any, text: Any, mapping: Any = None, header: Any = None,
                     lang: Optional[str] = None) -> Dict[str, Any]:
        """Rows copied from Excel read as trades of one product (:func:`entry.read_paste`) and each priced with the
        form's own checks: what would be kept (``ok``, ``trade``) and why not (``error``) - nothing is kept."""
        user = self.require_user(user)
        return self.et.call(self._bulk, user, kind, text, mapping, header, lang)

    def bulk_save(self, user: Optional[str], kind: Any, text: Any, mapping: Any = None, header: Any = None,
                  rows: Any = None, lang: Optional[str] = None) -> Dict[str, Any]:
        """Keep the valid rows of a paste - all of them in one transaction, or none.  ``rows``: the lines the preview
        showed as valid (what the user saw): if any of them is not valid now (a market moved, the text changed) nothing
        is kept (409, with the preview as it is now).  A row with an error is never kept; it is listed (``errors``)."""
        user = self.require_user(user)
        res = self.et.call_at(EngineThread.WRITE, self._bulk, user, kind, text, mapping, header, lang, True, rows)
        self.bump()
        return res

    def _bulk(self, user, kind, text, mapping=None, header=None, lang=None, save=False, confirmed=None) -> Dict[str, Any]:
        try:
            paste = entry.read_paste(text if isinstance(text, str) else "", str(kind or ""), mapping,
                                     None if header is None else _flag(header))
        except entry.EntryError as exc:
            raise ServiceError(str(exc))
        lang = lang or self.settings.locale
        found: Dict[int, List[Tuple[str, Dict[str, Any], Optional[str]]]] = {}
        for row in paste["rows"]:
            try:
                if paste["problems"]:
                    raise entry.EntryError("sütunlar: " + "; ".join(paste["problems"]))
                payload = entry.row_payload(paste["kind"], paste["columns"], row["cells"])
                found[row["n"]], row["trade"] = self._bulk_row(user, paste["kind"], payload, lang)
                row["ok"] = True
            except (entry.EntryError, bl.TradeError, ServiceError) as exc:
                row.update(ok=False, error=str(exc))
        paste["valid"] = len(found)
        paste["invalid"] = len(paste["rows"]) - len(found)
        if not save:
            return paste
        if confirmed is None:
            keep = [r["n"] for r in paste["rows"] if r["ok"]]
        else:
            try:
                wanted = {int(n) for n in confirmed}
            except (TypeError, ValueError):
                raise ServiceError("satır listesi anlaşılamadı")
            gone = sorted(n for n in wanted if n not in found)
            if gone:
                raise ServiceError("önizlemeden sonra geçerliliğini yitiren satır var (%s): hiçbir satır kaydedilmedi, yeniden bakın"
                                   % ", ".join("%d. satır" % n for n in gone), 409, data={"preview": paste})
            keep = [r["n"] for r in paste["rows"] if r["n"] in wanted]
        if not keep:
            raise ServiceError("kaydedilecek geçerli satır yok", data={"preview": paste})
        ids = self.store.add_trade_batch(self.today_iso(), [item for n in keep for item in found[n]], user)   # all, or none
        self._sync_blotter()
        return {"saved": len(keep), "rows": keep, "ids": ids, "kind": paste["kind"],
                "errors": [{"n": r["n"], "error": r["error"]} for r in paste["rows"] if not r["ok"]],
                "left": [r["n"] for r in paste["rows"] if r["n"] not in set(keep)]}

    def _bulk_row(self, user: str, kind: str, payload: Dict[str, Any], lang: str) -> Tuple[List[Tuple[str, Dict[str, Any], Optional[str]]], Dict[str, Any]]:
        """One pasted row priced as the form prices it: (what to keep - ``(kind, record, package)`` each -, what to show)."""
        if kind == "fwd":
            book = self._book("tto")
            try:
                rec = bl.forward_trade(book, self.interp.boot_overlay(user, book), self._fwd_payload(payload, lang))
            except bl.TradeError as exc:
                raise ServiceError(str(exc))
            return [("fwd", rec, None)], rec
        if kind == "ois":
            q, recs, package = self._ois_records(user, payload, lang)
            return [("ois", r, package) for r in recs], {"label": q["label"], "legs": q["legs"], "info": q["info"], "dv01": q["dv01"]}
        rec = self._bond_record(user, payload, lang)
        return [("bond", rec, None)], rec

    def bulk_from_forward(self, user: Optional[str], lang: Optional[str] = None) -> Dict[str, Any]:
        """TOPLU FORWARD FİYATLAMA's "İşleme al" (the Forward page, ``EK_BULK``; the desk, 24.11.2026: "3 ekle"): every
        row of ``user``'s own table with a Tutar as the rows "Excel'den yapıştır" reads (:func:`entry.bulk_forward_paste`)
        - the text the dialog opens with on FX Forward, the rows taken and left out, and each taken row's Tutar cell (the
        browser empties those of the rows the save kept).  Nothing is priced or saved here: the dialog's preview and its
        save (``bulk_preview`` / ``bulk_save``) are the paste's own."""
        user = self.require_user(user)
        return self.et.call(self._bulk_from_forward, user, lang or self.settings.locale)

    def _bulk_from_forward(self, user: str, lang: str) -> Dict[str, Any]:
        book = self._book("tto")
        if ex.BULK_SHEET not in book.model.sheet_index:
            raise ServiceError("TOPLU FORWARD tablosu yok (çalışma kitabına uymadığı için dışarıda bırakıldı)", 404)
        calc = self._calc(user, book)
        si = book.model.sheet_index[ex.BULK_SHEET]
        cols = {"date": "B", "ret_mid": "G", "manual": "L", "rate": ex.BULK_RATE, "usd_fwd": "N", "eur_fwd": "P", "usd_typed": "R",
                "eur_typed": "T", "pair": ex.BULK_PAIR, "dir": ex.BULK_DIR, "amount": ex.BULK_AMOUNT, "cpt": ex.BULK_CPT}
        spread_all = calc.get(si, *divmod(parse_a1(ex.BULK_SPREAD_ALL), COLS))          # (the table's general spread)
        # the row's typed value (its two-way group, twoway.py): which of Manuel TRY % / Spread / ON karşılık % / USDTRY fwd,
        # puan, P/gün / EURTRY fwd, puan, P/gün
        group = self.twoway.groups.get(ex.BULK_TW_ID)
        overlay = self._overlay(user, book)
        rows = []
        for k in range(ex.BULK_ROWS):
            r = ex.BULK_FIRST + k
            row: Dict[str, Any] = {key: calc.get(si, r, col_to_index(col)) for key, col in cols.items()}
            row.update(n=k + 1, ref="%s!%s%d" % (ex.BULK_SHEET, ex.BULK_AMOUNT, r), spread_all=spread_all)
            if group is not None:
                m = group.anchor(k, overlay, book.engine.input_value)
                row["anchor"] = index_to_col(m.cells[k][1] % COLS) if m is not None else None      # (its column)
            rows.append(row)
        return entry.bulk_forward_paste(rows, lang)

    def _cross_typed_forwards(self, user: str, book: Book, calc: Optional[Calc], written: Dict[Tuple[int, int], Any],
                              cleared: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """ÇAPRAZ FORWARD's manual forwards typed (its two-way group's forward store, ``extras.CROSS_TW_STORE`` of
        ``extras.CROSS_TW_ID``) that a write of its currency (``Forward!C197``) takes away: a forward typed is a forward of
        the currency it was typed in - another currency would read it as its own.  Only when the currency changes
        (``written`` / ``cleared``: the user's values of the write and the cells it takes back to their default; ``calc``:
        the user's calculation before it, None: made here); a forward typed in the same write stays, and so does a Manuel
        TRY % typed or a Manuel ON typed (26.11.2026): a TRY rate means the same in any currency."""
        g = self.twoway.groups.get(ex.CROSS_TW_ID)
        if g is None or g.book is not book:
            return []
        si, rc = book.cell("%s!%s" % (g.sheet, ex.CROSS_CCY))
        r, c = divmod(rc, COLS)
        if (si, rc) in written:
            new = written[(si, rc)]
        elif (si, rc) in cleared:
            new = book.engine.shared.get(si, r, c)            # (back to its default: the workbook's)
        else:
            return []
        if calc is None:
            calc = self._calc(user, book)
        if ex.cross_currency(calc.get(si, r, c)) == ex.cross_currency(new):
            return []
        ov = self._overlay(user, book)
        fwd = col_to_index(ex.CROSS_TW_STORE)
        return [cell for m in g.members if not m.own for cell in m.store
                if cell[1] % COLS == fwd and ov.get(cell) is not None and cell not in written]

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
        free = self._free_rows(current)
        if len(todo) > len(free):
            raise ServiceError("listede %d boş satır var, %d kâğıt eklenmek istendi" % (len(free), len(todo)))
        items = [{"ref": book.ref(*cells[k]), "value": code} for k, code in zip(free, todo)]
        res = self.set_inputs(user, book_id, items) if items else {"applied": 0, "errors": []}
        if res["errors"]:
            raise ServiceError("; ".join(res["errors"]))
        out = {"added": todo, "skipped": skipped, "cells": [i["ref"] for i in items], "free": len(free) - len(todo), "gen": self.gen}
        if res.get("row_values"):
            out["row_values"] = res["row_values"]                # (values left on a row with no bond: gone - rowkeys.py)
        if res.get("follow"):
            out["follow"] = res["follow"]                        # (the trading list's: the ASW list and Tüm Kâğıtlar too)
        return out

    @staticmethod
    def _free_rows(current: List[str]) -> List[int]:
        """The empty places of a list in the order bonds go into them: below its last bond first - the empty rows the
        desk keeps between its groups stay empty until there is no room left at the end."""
        last = max([k for k, v in enumerate(current) if v] or [-1])
        return [k for k, v in enumerate(current) if not v and k > last] + [k for k, v in enumerate(current) if not v and k < last]

    #: the trading list: the bonds of DİBS RV (and so of DİBS Trading)
    TRADING_LIST = ("tto", "DİBS RV!A5:A54")
    #: the ASW workbook's list of bonds (its curve and charts) follows the trading list: a bond that comes onto the trading
    #: list - ★, "+ ISIN ekle", typed or pasted - goes onto it too, one that leaves it (☆, ✕, its ISIN blanked or typed
    #: over) leaves it too; a bond the ASW page added itself stays until it is taken off there
    ASW_LIST = ("asw", "ASW!B7:B56")
    #: the store's key: the trading list's bonds were put on the ASW list once, at the first start of this version
    ASW_SYNCED = "migrated.asw_follows_trading"

    def _list_off(self, user: str, book_id: str, ref: str, codes: Sequence[str]) -> Tuple[int, Dict[str, Any]]:
        """Bonds off a list of bonds: their rows empty - what they held goes with them, for everyone (the source,
        everyone's manual price, coupon, repo, "Elle değer", in the saved scenarios too: rowkeys.py).  Returns the rows
        emptied and the write's result (``row_values``: what went; the trading list's ``follow``)."""
        book = self._book(book_id)
        cells = book.cells_of(ref)
        current = self._list_values(user, book_id, ref)
        rows = [cells[k] for k, v in enumerate(current) if v and v in codes]
        if not rows:
            return 0, {}
        res = self.set_inputs(user, book_id, [{"ref": book.ref(*c), "value": None} for c in rows])
        if res["errors"]:
            raise ServiceError("; ".join(res["errors"]))
        return len(rows), res

    def _asw_here(self) -> bool:
        """The ASW workbook's list of bonds is here (its book and its ISIN cells, inputs of the page)."""
        book_id, ref = self.ASW_LIST
        book = self.books.get(book_id)
        try:
            return book is not None and all(c in book.inputs for c in book.cells_of(ref))
        except (KeyError, ValueError):
            return False

    def _trading_before(self, book: Book, cells: Sequence[Tuple[int, int]]) -> Optional[List[str]]:
        """The trading list's ISINs before a write of the desk's values that touches its cells (None: it does not) -
        on the calculation thread, with the write."""
        if book.id != self.TRADING_LIST[0] or not cells:
            return None
        try:
            mine = set(book.cells_of(self.TRADING_LIST[1]))
        except (KeyError, ValueError):
            return None
        if not any(c in mine for c in cells):
            return None
        return self.rowkeys.keys("dibs")

    def _trading_after(self, before: List[str], res: Dict[str, Any]) -> None:
        """What a write did to the trading list: the bonds that came onto it and the ones that left it (``trading`` of
        the result; :meth:`_follow_trading` takes the other lists along, off the calculation thread).  A bond moved
        within the list in one write (a paste re-sorting it) is neither."""
        after = self.rowkeys.keys("dibs")
        entered = [c for c in dict.fromkeys(after) if c and c not in before]
        left = [c for c in dict.fromkeys(before) if c and c not in after]
        if entered or left:
            res["trading"] = {"entered": entered, "left": left}

    def _follow_trading(self, user: str, res: Dict[str, Any]) -> None:
        """After a write that changed the trading list: the ASW list and Tüm Kâğıtlar follow it (``follow`` of the
        result says what they did; what the ASW list's rows held and where it went joins ``row_values``)."""
        change = res.pop("trading", None)
        if not change:
            return
        from .rowkeys import merge_notes
        try:
            follow, notes = self._trading_follows(user, change["entered"], change["left"])
        except Exception as exc:  # noqa: BLE001 - the trading list is written: what could not follow is said, not raised
            self.ops.failure("trading listesini izleyen listeler (DİBS ASW, Tüm Kâğıtlar)", exc)
            why = str(exc)[:200] or type(exc).__name__
            res["follow"] = {"errors": [why], "text": "DİBS ASW / Tüm Kâğıtlar trading listesini izleyemedi: " + why}
            return
        told = merge_notes([x for x in (res.get("row_values"), notes) if x])
        if told:
            res["row_values"] = told
        if follow:
            res["follow"] = follow

    def _trading_follows(self, user: str, entered: Sequence[str], left: Sequence[str]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """The ASW list and Tüm Kâğıtlar with the trading list: the bonds that ``left`` it off the ASW list (with their
        rows' values, for everyone), the ones that ``entered`` it onto the ASW list (below its last bond; the ones it
        has no room for stay on the trading list only) and onto Tüm Kâğıtlar when that does not have them (Bloomberg
        tells their kind, as its "+ ISIN ekle" does).  Text that is no ISIN goes nowhere.  Returns what was done
        (``asw_added``, ``asw_removed``, ``asw_full``, ``desk_added``, ``desk_waiting``, ``desk_refused``, ``invalid``,
        ``text``) and what the ASW list's rows held and where it went."""
        valid = [c for c in entered if bd.isin_valid(c)]
        out: Dict[str, Any] = {"invalid": [c for c in entered if not bd.isin_valid(c)]}
        notes = None
        if self._asw_here():
            got = self._asw_follow(user, valid, left)
            out.update(asw_added=got["added"], asw_removed=got["removed"], asw_full=got["full"])
            notes = got["row_values"]
            if got["errors"]:
                out["asw_errors"] = got["errors"]
        listed = {b["isin"] for b in bd.listed(self._bond_day())}
        new = [c for c in valid if c not in listed]
        if new:
            desk = self.bond_list_add(user, new)
            out.update(desk_added=[x["isin"] for x in desk["added"]], desk_waiting=list(desk["waiting"]),
                       desk_refused=[{"isin": x["isin"], "text": x["text"]} for x in desk["refused"]])
        out = {k: v for k, v in out.items() if v}
        if out:
            out["text"] = self._follow_text(out)
        return out, notes

    def _asw_follow(self, user: str, entered: Sequence[str], left: Sequence[str]) -> Dict[str, Any]:
        """The ASW list in one write: the rows of the bonds that ``left`` the trading list emptied, the ones that
        ``entered`` it below the list's last bond (into the rows between when the end is full) - each once, the ones
        listed already skipped, the ones there is no room for left out (``full``)."""
        book_id, ref = self.ASW_LIST
        book = self.books[book_id]
        cells = book.cells_of(ref)
        current = self._list_values(user, book_id, ref)
        now = list(current)
        items: List[Dict[str, Any]] = []
        removed: List[str] = []
        for k, v in enumerate(current):
            if v and v in left:
                now[k] = ""
                items.append({"ref": book.ref(*cells[k]), "value": None})
                if v not in removed:
                    removed.append(v)
        todo = [c for c in dict.fromkeys(entered) if c not in now]
        free = self._free_rows(now)
        fit, full = todo[:len(free)], todo[len(free):]
        items += [{"ref": book.ref(*cells[k]), "value": code} for k, code in zip(free, fit)]
        res = self.set_inputs(user, book_id, items) if items else {"errors": []}
        return {"added": fit, "removed": removed, "full": full, "row_values": res.get("row_values"),
                "errors": list(res.get("errors") or [])}

    @staticmethod
    def _bond_name(code: str) -> str:
        """A bond as a toast names it: as the desk does ("15.03.28", "19.01.28 TLREF"), else its ISIN."""
        b = bd.by_isin(code)
        return bd.short_label(b) if b and b.get("maturity") else code

    def _follow_text(self, f: Dict[str, Any]) -> str:
        """What the ASW list and Tüm Kâğıtlar did with a change of the trading list, as the toast says it."""
        def names(codes: Sequence[str]) -> str:
            return ", ".join(self._bond_name(c) for c in codes)
        parts = []
        if f.get("asw_added"):
            parts.append("DİBS ASW'ye de eklendi: " + names(f["asw_added"]))
        if f.get("asw_removed"):
            parts.append("DİBS ASW'den de çıkarıldı: " + names(f["asw_removed"]))
        if f.get("asw_full"):
            parts.append("DİBS ASW listesinde yer yok: %s yalnız trading listesine girdi" % names(f["asw_full"]))
        if f.get("asw_errors"):
            parts.append("DİBS ASW listesine yazılamadı: " + "; ".join(f["asw_errors"]))
        if f.get("desk_added"):
            waiting = [c for c in f["desk_added"] if c in (f.get("desk_waiting") or ())]
            parts.append("Tüm Kâğıtlar'a eklendi: " + names(f["desk_added"])
                         + (" (türü Bloomberg'den bekleniyor: %s)" % names(waiting) if waiting else ""))
        if f.get("desk_refused"):
            parts.append("Tüm Kâğıtlar'a alınmadı: " + ", ".join("%s (%s)" % (x["isin"], x["text"]) for x in f["desk_refused"]))
        if f.get("invalid"):
            parts.append("ISIN değil, DİBS ASW'ye ve Tüm Kâğıtlar'a gitmedi: " + ", ".join(f["invalid"]))
        return " · ".join(parts)

    def _asw_follows_once(self) -> None:
        """Once, at the first start of this version: a bond of the trading list that the ASW list does not have goes
        onto it (below its last bond, as ★ puts it); from then on the ASW list follows every change of the trading list.
        Said in the log (on the desk's data both lists held the same bonds: nothing moves)."""
        if self.store.get(self.ASW_SYNCED) or not self._asw_here():
            return
        book_id, ref = self.ASW_LIST
        book = self.books[book_id]
        trading = [c for c in dict.fromkeys(self.rowkeys.keys("dibs")) if c and bd.isin_valid(c)]
        current = self.rowkeys.keys("asw")
        missing = [c for c in trading if c not in current]
        free = self._free_rows(current)
        cells = book.cells_of(ref)
        items = [{"ref": book.ref(*cells[k]), "value": code} for k, code in zip(free, missing)]
        if items:
            res = self._set_inputs(None, book_id, items, False)
            log.info("DİBS ASW listesi trading listesini izliyor (bir kereye mahsus): trading listesinin ASW'de olmayan %d kâğıdı "
                     "eklendi - %s%s", len(items), ", ".join("%s → %s" % (i["value"], i["ref"]) for i in items),
                     " · hata: " + "; ".join(res["errors"]) if res.get("errors") else "")
        else:
            log.info("DİBS ASW listesi trading listesini izliyor: trading listesinin %d kâğıdı ASW listesinde zaten var", len(trading))
        if len(missing) > len(free):
            log.warning("DİBS ASW listesinde yer yok: %s ASW listesine eklenemedi", ", ".join(missing[len(free):]))
        self.store.put(self.ASW_SYNCED, now_iso())

    def bond_flag(self, user: str, isin: str, on: bool) -> Dict[str, Any]:
        """★ a bond: onto the trading list (below its last bond) or off it - for everyone, the ASW list with it (and Tüm
        Kâğıtlar, for a bond it does not have).  A bond taken off leaves its rows empty, with nothing of it left behind
        (its source, everyone's manual price, coupon, repo, "Elle değer" - in the saved scenarios too).  ``asw``: the ASW
        list took it / let it go (None: no ASW list here); ``follow``: what the other lists did; ``row_values``: what of
        the rows' values moved / went (rowkeys.py)."""
        from .rowkeys import merge_notes
        user = self.require_user(user)
        code = "".join(str(isin or "").split()).upper()
        if not bd.isin_valid(code):
            raise ServiceError("ISIN değil ya da kontrol hanesi tutmuyor: %s" % (code or "(boş)"))
        book_id, ref = self.TRADING_LIST
        asw_here = self._asw_here()
        if on:
            res = self.list_add(user, book_id, ref, [code])
            follow, told = res.get("follow") or {}, res.get("row_values")
            if not res["added"]:
                # on the trading list already: the ASW list and Tüm Kâğıtlar have it still, as ★ always made sure
                follow, notes = self._trading_follows(user, [code], [])
                told = merge_notes([x for x in (told, notes) if x])
            out = {"isin": code, "on": True, "added": bool(res["added"]), "cells": res["cells"],
                   "asw": code in (follow.get("asw_added") or ()) if asw_here else None, "gen": self.gen}
        else:
            removed, res = self._list_off(user, book_id, ref, [code])
            follow, told = res.get("follow") or {}, res.get("row_values")
            self.bump()
            out = {"isin": code, "on": False, "removed": removed,
                   "asw": code in (follow.get("asw_removed") or ()) if asw_here else None, "gen": self.gen}
        if follow:
            out["follow"] = follow
        if told:
            out["row_values"] = told
        return out

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

    #: the store's key of Tüm Kâğıtlar's rows: ``{"rows": {isin: row}, "freed": {row: the day it was left}}`` - a bond
    #: keeps its row across restarts (an alarm, an "Elle değer", a formula on its row stays its own); a new bond takes a
    #: row no bond had yet, else the one left longest ago
    UNI_KEPT = "bonds.rows"

    def _sync_universe(self) -> bool:
        """Tüm Kâğıtlar's rows, one a bond of the desk's list (on the calculation thread): a bond keeps its row - after a
        restart too -, a new one takes a free row (the kinds in their order, by maturity; a row no bond had first, then
        the one left longest ago), a bond gone leaves its row empty and what was typed on it goes with it (rowkeys.py).
        True when a cell changed."""
        book = self.books.get("tto")
        if book is None or ex.UNI_SHEET not in book.model.sheet_index:
            return False
        si = book.model.sheet_index[ex.UNI_SHEET]
        self._uni_day = self._bond_day()
        self._uni_note = None
        listed = bd.listed(self._uni_day)
        want = {b["isin"]: b for b in listed}
        before = dict(self._uni_rows)
        rows = {isin: r for isin, r in before.items() if isin in want and ex.UNI_FIRST <= r <= ex.UNI_LAST}
        taken = set(rows.values())
        freed = {r: d for r, d in self._uni_freed.items() if r not in taken}
        free = sorted((r for r in range(ex.UNI_FIRST, ex.UNI_LAST + 1) if r not in taken),
                      key=lambda r: (r in freed, freed.get(r, ""), r))
        order = {k: i for i, (k, _, _) in enumerate(ex.UNI_KINDS)}
        for b in sorted(listed, key=lambda x: (order.get(x.get("kind"), len(order)), x.get("maturity") or "9999", x["isin"])):
            if b["isin"] not in rows and free:
                rows[b["isin"]] = free.pop(0)
        day = self._uni_day.isoformat()
        for isin, r in before.items():
            if rows.get(isin) != r and r not in rows.values() and ex.UNI_FIRST <= r <= ex.UNI_LAST:
                freed[r] = day
        for r in rows.values():
            freed.pop(r, None)
        if rows != before or freed != self._uni_freed or not self._uni_kept:
            if self._uni_kept:
                self._uni_note = self.rowkeys.universe(book, before, rows)
            self.store.put(self.UNI_KEPT, {"rows": rows, "freed": {str(r): d for r, d in sorted(freed.items())}})
            self._uni_kept = True
        self._uni_freed = freed
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
        off = self.bond_flag(user, code, False)
        with self._desk_lock:
            desk = self._desk_now()
            desk["removed"][code] = {"by": user, "at": now_iso()}
            self._save_desk(desk)
        uni = self.et.call(lambda: (self._sync_universe(), self._uni_note)[1])
        self.bump()
        out = {"isin": code, "removed": True, "trading": off["removed"] > 0, "gen": self.gen}
        from .rowkeys import merge_notes
        told = merge_notes([x for x in (off.get("row_values"), uni) if x])
        if told:
            out["row_values"] = told                     # (what was typed on its rows went with it)
        if off.get("follow"):
            out["follow"] = off["follow"]                # (off the trading list: off the ASW list too)
        return out

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
        for a bond on the trading list whose price there is no live quote, DİBS RV's yield, its O/N equivalent, ASW and signal
        soft."""
        rv = book.model.sheet_index.get("DİBS RV")
        soft = [index_to_col(ex._col("N") + k) for k, (col, _, _) in enumerate(ex.UNI_RV) if col != "AI"] + [ex.UNI_ON[0]]   # not DV01
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
    #: the trading summary's column of the yield's O/N equivalent (DİBS RV's BO; the desk, 26.11.2026), beside the yield
    ON_HEAD = "ON karşılık %"

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

    def _trading_columns(self) -> List[Tuple[str, List[Tuple[str, str, str]]]]:
        """The trading summary's columns in their groups: ``[(group, [(caption, key, tip), ...]), ...]``.  A column's key
        is its letter in the table as it was before the groups (what a user hid, or a launchpad box shows, stays that
        column); the columns that came with the groups follow the old ones.  The FX swap group is on the FX swap implied TRY
        curve (DİBS ASW's "ASW FX", ``rvfair.FX``)."""
        from . import rvfair
        board = len(self._BOARD_HEADS)
        old = {k: index_to_col(k + 1) for k in range(19 + board + 1)}          # A .. S, the board, Kart
        new = [index_to_col(20 + board + 1 + k) for k in range(8)]             # (the yield's O/N equivalent the 8th: 26.11.2026)
        fair = ("Kâğıdın ASW'si DİBS RV'nin %s ASW eğrisinde (a + b·t + c·t², sabit kuponlulara uydurulan) dursaydı %s: kirli "
                "@spot = PV@%s − eğri ASW × annuity / 100, valöre fonlama çarpanıyla, temizi − işlemiş faiz; getiri ekrandaki gibi "
                "BIST bileşik. Bono eğriye girmez: eğrinin kâğıdın vadesindeki değeri. TLREF / FRN / TÜFE: yok (nedeni üzerinde)")
        fx_fair = ("Kâğıdın ASW FX'i DİBS ASW'nin ASW eğrisinde (a + b·t + c·t², sayfanın Eğri / grafik kuralıyla uydurulan; "
                   + rvfair.FX_CURVE_TEXT + ") dursaydı %s: kirli @spot = PV − eğri ASW × annuity / 100 (DİBS ASW), valöre fonlama "
                   "çarpanıyla, temizi − işlemiş faiz; getiri ekrandaki gibi BIST bileşik (DİBS RV'nin nakit akışlarıyla). TLREF / "
                   "FRN / TÜFE: yok (nedeni üzerinde)")
        return [
            ("", [("★", old[0], "Trading listesinden çıkar (herkes için; DİBS ASW listesinden de)"),
                  ("Kâğıt", old[1], ""), ("ISIN", old[2], ""), ("Vade", old[3], ""),
                  ("Kalan yıl", old[4], "Bugünden vadeye yıl (365,25 gün)")]),
            ("Fiyat", [("Valör", old[5], "Kâğıdın DİBS RV'de fiyatlandığı Bloomberg kaynağı (ISL0: aynı gün valör, ISL1: ertesi iş günü)"),
                       ("Bid", old[6], "DİBS RV: Bloomberg alış ('–': o tarafta emir yok)"),
                       ("Ask", old[7], "DİBS RV: Bloomberg satış ('–': o tarafta emir yok)"),
                       ("Son işlem", old[8], "Son işlem fiyatı (DİBS RV)"),
                       ("Ne zaman", old[9], "Son işlemin günü; canlıda dashboard'un işlemi gördüğü saat")]),
            ("OIS'e göre", [("Getiri %", old[10], "DİBS RV: BIST bileşik getiri (kullanılan temiz fiyattan)"),
                            (self.ON_HEAD, new[7], "DİBS RV: getirinin TLREF'in kuralıyla gecelik karşılığı - valörden vadeye, iş "
                                                   "günlerinde bileşik (ACT/365; hafta sonu / tatilde son iş gününün faizi aradaki "
                                                   "günler için tek adımda), TLREF ve repoyla karşılaştırılır · sabit kuponlu ve bono"),
                            ("ASW / DM", old[11], "DİBS RV: TLREF OIS eğrisine göre ASW (bp; sabit kuponlu, bono) · TLREF'e endeksli kâğıtta DM"),
                            ("Adil getiri %", new[0], fair % ("OIS", "getirisi", "OIS")),
                            ("Adil fiyat", new[1], fair % ("OIS", "valördeki temiz fiyatı", "OIS")),
                            ("Pahalı / ucuz", old[12], "DİBS RV: ASW − eğrinin ASW'si (bp; + ucuz) · sabit kuponlu"),
                            ("Sinyal", old[13], "DİBS RV: pahalı / ucuz eşiği (Eşik bp) aşınca UCUZ / PAHALI")]),
            ("FX swap'a göre", [("ASW FX", new[2], "DİBS ASW: ASW (bp), " + rvfair.FX_CURVE_TEXT),
                                ("Adil getiri %", new[3], fx_fair % "getirisi"),
                                ("Adil fiyat", new[4], fx_fair % "valördeki temiz fiyatı"),
                                ("Pahalı / ucuz", new[5], "DİBS ASW: ASW FX − FX eğrisinin ASW'si (bp; + ucuz)"),
                                ("Sinyal", new[6], "Pahalı / ucuz DİBS RV'nin eşiğini (Eşik bp) aşınca UCUZ / PAHALI")]),
            ("Risk", [("Mod. süre", old[14], "DİBS RV: modifiye süre"),
                      ("DV01 / 1mn", old[15], "DİBS RV: 1 mn nominalin DV01'i (TL; TLREF'te spread DV01'i)"),
                      (self.USD_DV01_HEAD, old[16], "DV01'i 1.000 USD olan TL nominal: 1.000 × USDTRY ÷ DV01 / 1mn, 5 mn'a yuvarlı")]),
            ("Carry", [("C+R (bp)", old[17], "DİBS RV: carry + roll-down (DİBS RV'nin Ufuk (ay) ayarıyla)"),
                       ("T0→T1 repo %", old[18], "T0 ve T1 kirli fiyatlarının ima ettiği O/N repo (aynı güne ait fiyatlardan)")]),
            ("Broker", [(h, old[19 + k], tip) for k, (h, tip) in enumerate(self._BOARD_HEADS)]),
            ("", [("Kart", old[19 + board], "Kâğıdın bütün bilgisi tek pencerede")]),
        ]

    def _fair_cells(self, f: Dict[str, Any], side: str, fits: Dict[str, Any], valor: Any, own: Any, loc) -> List[Dict[str, Any]]:
        """A bond's fair yield and fair clean price on one of the fitted ASW curves (rvfair.py: DİBS RV's OIS curve, DİBS
        ASW's FX swap implied one), with how each is made in the tip; a dash that says why where there is none.  ``own``:
        the bond's own yield, said beside the fair one."""
        from . import rvfair
        if "yield" not in f:
            why = ("OIS eğrisine göre adil değer yok: %s" if side == "ois" else rvfair.FX_CURVE_TEXT + ": adil değer yok – %s") % (f.get("why") or "")
            dash = {"t": "–", "k": "s", "al": "r", "cls": "soft", "tip": why}
            return [dict(dash), dict(dash)]

        def n(v: float, fmt: str) -> str:
            return numfmt.format_value(v, fmt, loc)

        a, b, c = fits[side]["coef"]
        poly = n(a, "0.0") + "".join((" − " if x < 0 else " + ") + n(abs(x), fmt) + t
                                     for x, fmt, t in ((b, "0.00", "·t"), (c, "0.000", "·t²")))
        parts = []
        if f["bill"]:
            parts.append("Bono eğriye girmez: eğrinin vadesindeki değeri")
        span = fits[side]["span"]
        if f["stretched"]:
            parts.append("eğrinin kâğıtları %s yıl: bu vade dışında, eğri uzatıldı" % ("–".join(n(x, "0.00") for x in span) if span else "yok"))
        curve = "OIS ASW eğrisi (%d kâğıt)" % fits[side]["n"] if side == "ois" else             "DİBS ASW'nin ASW eğrisi (%d kâğıt; %s)" % (fits[side]["n"], rvfair.FX_CURVE_TEXT)
        parts.append("%s: %s; t = %s yıl → eğri ASW %s bp" % (curve, poly, n(f["t"], "0.00"), n(f["asw"], "0.0")))
        parts.append("kirli @spot = PV@%s %s − eğri ASW × annuity %s / 100 = %s" % ("OIS" if side == "ois" else "FX", n(f["pv"], "0.000"),
                                                                                   n(f["ann"], "0.0000"), n(f["dirty_spot"], "0.000")))
        when = " (%s)" % n(valor, "dd.mm.yyyy") if type(valor) is float else ""
        parts.append("valörde%s ÷ fonlama %s: kirli %s, temiz %s (işlemiş %s)" % (when, n(f["dd"], "0.00000"), n(f["dirty"], "0.000"),
                                                                                    n(f["price"], "0.000"), n(f["acc"], "0.000")))
        parts.append("getiri %s (BIST bileşik%s)" % (n(f["yield"], "0.00%"), "; ekranda %s" % n(own, "0.00%") if type(own) is float else ""))
        tip = " · ".join(parts)
        cls = "soft" if f["stretched"] else ""
        out = [{"t": n(f["yield"], "0.00%"), "v": f["yield"], "k": "n", "tip": tip},
               {"t": n(f["price"], "0.000"), "v": f["price"], "k": "n", "tip": tip}]
        if cls:
            for x in out:
                x["cls"] = cls
        return out

    def _fx_curve(self, user: Optional[str]):
        """DİBS ASW's sheet on the FX swap implied TRY curve as ``rvfair`` reads it (the calculation behind DİBS ASW's "ASW
        FX" column and its FX swap chart, over the user's own inputs) - None without the ASW book or any FX swap price."""
        from . import rvfair
        book = self.books.get("asw")
        if book is None or rvfair.FX_SHEET not in book.model.sheet_index or ex.FXC_SHEET not in book.model.sheet_index:
            return None
        calc, swapped = self._asw_fx_calc(book, user)
        if calc is None:
            return None
        si = book.model.sheet_index[rvfair.FX_SHEET]
        return rvfair.FxCurve(calc, si, rvfair.fx_rows(calc, si), swapped)

    @staticmethod
    def _fx_cells(f: Dict[str, Any], threshold: Any, loc) -> List[Dict[str, Any]]:
        """A bond's own figures on the FX swap implied curve as DİBS ASW has them (rvfair's FX side): its ASW, the fitted
        curve's ASW at its years, cheap / rich (+ cheap) and the signal at DİBS RV's threshold - empty cells (the reason
        in the tip of the first) where there are none."""
        from . import rvfair
        src = "DİBS ASW · " + rvfair.FX_CURVE_TEXT

        def bp(key: str) -> Dict[str, Any]:
            v = f.get(key)
            return {"t": numfmt.format_value(v, "0.0", loc), "v": v, "k": "n", "tip": src} if type(v) is float else {"t": "", "k": ""}

        own = bp("own")
        if own["t"] == "" and f.get("why"):
            own = {"t": "–", "k": "s", "al": "r", "cls": "soft", "tip": "FX swap ASW'si yok: %s" % f["why"]}
        sig = rvfair.signal(f.get("rich"), threshold)
        th = threshold if type(threshold) is float else 0.0
        sig_cell = {"t": sig, "k": "s", "b": 1, "tip": "Pahalı / ucuz %s bp eşiğini aşınca (DİBS RV: Eşik bp)"
                    % numfmt.format_value(th, "0" if th == int(th) else "0.0", loc)} if sig else {"t": "", "k": ""}
        return [own, bp("curve"), bp("rich"), sig_cell]

    def _trading_table(self, user: Optional[str], loc) -> Dict[str, Any]:
        """The trading list at a glance (generated): the bonds of DİBS RV kind by kind, by maturity, in groups of
        columns - the price on the value date the bond is priced on (bid, ask, the last trade and when); against OIS what
        DİBS RV makes of it (yield, ASW, cheap / rich, signal), against the FX swap implied curve what DİBS ASW makes of it
        (ASW, cheap / rich; DİBS RV's threshold for the signal) and its fair yield and price on each fitted ASW curve
        (rvfair.py); its risk (duration, DV01, the nominal of USD 1,000 DV01); carry and the repo
        T0 -> T1 implies; today's chat board."""
        from . import rvfair
        book = self.books.get("tto")
        groups = self._trading_columns()
        cols = [x for _, items in groups for x in items]
        width = len(cols)
        top: List[Dict[str, Any]] = []
        group_tips = {"FX swap'a göre": "DİBS ASW'nin ASW FX hesabı: " + rvfair.FX_CURVE_TEXT}
        for name, items in groups:
            top.append(dict({"t": name, "k": "s", "b": 1, "f": "hd", "al": "c"} if name else {"t": "", "k": ""},
                            **({"cs": len(items)} if len(items) > 1 else {}), **({"tip": group_tips[name]} if name in group_tips else {})))
            top.extend({"sk": 1} for _ in items[1:])
        head = [dict({"t": cap, "k": "s", "b": 1, "f": "hd"}, **({"tip": tip} if tip else {})) for cap, _, tip in cols]
        rows: List[List[Dict[str, Any]]] = [top, head]
        out = {"rows": rows, "r": [], "c": [key for _, key, _ in cols], "added": width}
        if book is None or "DİBS RV" not in book.model.sheet_index:
            out["r"] = [0, 1]
            return out
        si = book.model.sheet_index["DİBS RV"]
        calc = self._calc(user, book)
        R = self.renderers[book.id]
        live = book.model.sheet_index.get(ex.LIVE_SHEET)
        said = self._board_bonds(user)
        today = _dt.date.fromisoformat(self.today_iso())
        spot = self._usdtry_mid(book, calc)
        fx = self._fx_curve(user)
        fits = rvfair.read_fits(calc, si, fx)
        threshold = calc.get(si, 2, parse_a1("P1") % COLS)

        def cell(c: str, r: int, s: int = si) -> Dict[str, Any]:
            got = R.cell(calc, s, r, parse_a1("%s1" % c) % COLS, loc)
            keep = {k: got[k] for k in ("t", "v", "k", "c", "b") if k in got}
            keep.setdefault("t", "")
            keep.setdefault("k", "")
            return keep

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
            # what DİBS RV works out of the price in use - and DİBS ASW on the FX swap implied curve: soft while no live
            # quote stands behind it
            f = rvfair.fair(calc, si, r, fits, fx)
            fx_own, _, fx_rich, fx_signal = self._fx_cells(f["fx"], threshold, loc)
            priced = {k: cell(c, r) for k, c in (("K", "T"), ("L", "Z"), ("M", "AB"), ("N", "AC"), ("on", ex.RV_ON[0][0]))}
            priced.update({"fx": fx_own, "fx_rich": fx_rich, "fx_signal": fx_signal})
            priced["N"] = dict(priced["N"], b=1)
            if q["stale"]:
                priced = {k: self._soft(c, q["tip"]) for k, c in priced.items()}
            valor, own = calc.get(si, r, parse_a1("P1") % COLS), calc.get(si, r, parse_a1("T1") % COLS)
            ois_y, ois_p = self._fair_cells(f["ois"], "ois", fits, valor, own, loc)
            fx_y, fx_p = self._fair_cells(f["fx"], "fx", fits, valor, own, loc)
            by = {"A": self._flag_cell(code, True), "B": label, "C": {"t": code, "k": "s", "cls": "soft"}, "D": due,
                  "E": {"t": numfmt.format_value(years, "0.00", loc), "v": years, "k": "n"} if years is not None else {"t": "", "k": ""},
                  "F": {"t": str(src or ""), "k": "s", "cls": "soft"},
                  "G": self._quote_cell(cell("K", r), q["bid"], q["raw_bid"], "bid", loc),
                  "H": self._quote_cell(cell("L", r), q["ask"], q["raw_ask"], "ask", loc), "I": dict(cell("AS", r), b=1), "J": when,
                  "K": priced["K"], "L": priced["L"], "M": priced["M"], "N": priced["N"],
                  "O": cell("AG", r), "P": cell("AI", r),
                  "Q": self._usd_dv01_cell(calc.get(si, r, parse_a1("AI1") % COLS), spot, kind, loc),
                  "R": cell("AO", r), "S": self._repo_cell(cell, live, r)}
            ois_keys = {cap: key for cap, key, _ in groups[2][1]}
            fx_keys = [key for _, key, _ in groups[3][1]]
            by.update({ois_keys[self.ON_HEAD]: priced["on"], ois_keys["Adil getiri %"]: ois_y, ois_keys["Adil fiyat"]: ois_p,
                       fx_keys[0]: priced["fx"], fx_keys[1]: fx_y, fx_keys[2]: fx_p,
                       fx_keys[3]: priced["fx_rich"], fx_keys[4]: priced["fx_signal"]})
            board = self._bond_cells(said.get(code), loc)
            for (_, key, _), c in zip(groups[6][1], board):
                by[key] = c
            by[groups[7][1][0][1]] = {"t": "▸", "k": "s", "cls": "act cardlink", "tip": "Kâğıt kartı: " + code}
            line =[by[key] for _, key, _ in cols]
            group = kind if kind in bonds else "S"
            bonds[group].append((mat if type(mat) is float else 1e9, line))
        for g, caption in self._TYPE_GROUPS:
            if not bonds[g]:
                continue
            rows.append([{"t": "%s · %d" % (caption, len(bonds[g])), "k": "s", "b": 1, "cls": "grouphead", "cs": width}]
                        + [{"t": "", "k": ""} for _ in range(width - 1)])
            rows.extend(line for _, line in sorted(bonds[g], key=lambda x: x[0]))
        if len(rows) == 2:
            rows.append([{"t": "Trading listesi boş: Tüm Kâğıtlar sayfasında ☆ ile ekleyin", "k": "s", "cls": "soft", "cs": width}]
                        + [{"t": "", "k": ""} for _ in range(width - 1)])
        # the rows are numbered as before the groups of columns (the captions 1, then a row each): a launchpad box that
        # keeps rows of it by their number shows the same ones; the groups' row above is a caption of the dashboard's (0)
        out["r"] = [0] + list(range(1, len(rows)))
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

    #: a trade's target / stop alarm is the trade's: changed or cleared in Trades
    TRADE_ALARM = "bu alarm Trades'teki #%s işleminin %s alarmı: Trades'te işlemin hedef / stop kutusunu boşaltın ya da değiştirin"

    def _trade_alarm(self, a: Optional[Dict[str, Any]]) -> None:
        tr = (a or {}).get("trade")
        if isinstance(tr, dict):
            raise ServiceError(self.TRADE_ALARM % (tr.get("id"), "hedef" if tr.get("which") == "target" else "stop"))

    def alarm_remove(self, user: str, alarm_id: str) -> Dict[str, Any]:
        user = self.require_user(user)
        self._trade_alarm(next((x for x in self.watch.alarms(user) if x["id"] == str(alarm_id or "")), None))
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
        self._trade_alarm(a)

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
        if self.mode == "live":
            self._tell_desk_hours()                      # Bloomberg's hours may have changed: at once
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

    # ================================================================== the morning meeting, DV01 Risk (28.11.2026, K5)
    def watch_reference(self, user: str) -> Dict[str, Any]:
        """"Referansı şimdi al" - İzleme's and Eğri Hareketi's reference at once (``Watch.reference``; the desk: A11)."""
        user = self.require_user(user)
        res = self.et.call(self.watch.reference, user)
        self.bump()
        return res

    def _kontrol_chips(self, book: Book, calc: Calc, data: Optional[Dict[str, Any]]) -> None:
        """Masa's Kontrol strip (``bugun.KONTROL``; the desk, 28.11.2026: A10): each chip's state (``kchip`` and
        ``k-tamam`` / ``k-uyari`` / ``k-hata``: below 1500 px only those not "tamam" show), its rule and where it leads in
        its tooltip, a click on it to the table it checks (``golink`` and ``go:#/<page>?p=<panel>``: golink.js), and a
        last cell "N tamam" (shown below 1500 px)."""
        from .bugun import KONTROL_SHEET, kontrol_read
        if not data or not data.get("rows") or KONTROL_SHEET not in book.model.sheet_index:
            return
        si = book.model.sheet_index[KONTROL_SHEET]
        chips = {c["col"]: c for c in kontrol_read(lambda addr: calc.get(si, *divmod(parse_a1(addr), COLS)))}
        cols = data.get("c") or []
        ok = []
        for row in data["rows"]:
            for j, cell in enumerate(row):
                c = chips.get(cols[j]) if j < len(cols) else None
                if c is None or not isinstance(cell, dict) or cell.get("sk"):
                    continue
                state = {0: "tamam", 1: "uyari", 2: "hata"}.get(c["code"], "hata")
                cls = ["kchip", "k-" + state] + (["kchip-all"] if c["col"] == "B" else [])
                if c["href"]:
                    cls += ["golink", "go:" + c["href"]]
                cell["cls"] = " ".join(cls)
                cell["tip"] = c["rule"] + (" Durum: %s." % c["state"]) + ("\nTıklayın → %s" % c["where"] if c["where"] else "")
                if c["col"] != "B" and c["code"] == 0:
                    ok.append(c["name"])
        # K2's quote age (C4, 28.11.2026): the old prices on the screens as one more chip - red when any (Ops.quotes);
        # only with prices that have a time (live: none in replay), in market hours and with the setting above 0
        q = self.ops.quotes()
        if q.get("minutes") and q.get("market") and q.get("of"):
            old = int(q.get("old") or 0)
            tip = ("Piyasa saatinde %d dk değişmeyen fiyat eski sayılır (Ayarlar › Alarmlar)." % q["minutes"]
                   + (" En eskiler: " + ", ".join("%s %s (%d dk)" % (o["ticker"], o["at"], o["min"]) for o in q["oldest"])
                      if old else ""))
            cols = list(cols) + ["Kota yaşı"]
            data["added"] = int(data.get("added") or 0) + 1
            for k, row in enumerate(data["rows"]):
                row.append({"t": "%d eski kota" % old if old else "Kotalar taze", "k": "s", "tip": tip,
                            "cls": "kchip " + ("k-hata" if old else "k-tamam")} if k == 0 else {"t": "", "k": ""})
            if not old:
                ok.append("Kota yaşı")
        data["c"] = list(cols) + ["Tamam"]
        data["added"] = int(data.get("added") or 0) + 1
        for k, row in enumerate(data["rows"]):
            row.append({"t": "%d tamam" % len(ok), "k": "s", "cls": "kchip-sum", "tip": "Tamam olan kontroller: "
                        + (", ".join(ok) or "yok") + " (geniş ekranda hepsi şeritte)"} if k == 0 else {"t": "", "k": ""})

    def _dv01_paste_column(self, user: Optional[str], data: Optional[Dict[str, Any]]) -> None:
        """DV01 Risk's pinned Parametreler: when the user last pasted their position - "yapıştırıldı 28.11 09:12", red when
        not today (``varrisk.paste_stamp``; the desk, 28.11.2026: A8) - a column of its own at the row's end."""
        from . import varrisk as vr
        if not data or not data.get("rows"):
            return
        st = vr.paste_stamp(self.store, user, self.today_iso())
        tip = ("Pozisyonun (VaR sekmesindeki Onshore / TLREF / Offshore kolonları, Pozisyon'daki C) en son yazıldığı an: %s%s"
               % (st["at"], "" if st["today"] else " - bugün değil: dünkü pozisyon olabilir") if st["at"]
               else "Pozisyon yapıştırılmadı: Murex'in Onshore / TLREF kolonlarını VaR sekmesine yapıştırın")
        cell = {"t": st["text"], "k": "s", "b": 1, "tip": tip, "cls": "dv01-paste"}
        if st["at"] and not st["today"]:
            cell["c"] = "neg"
        elif not st["at"]:
            cell["c"] = "mute"
        data["c"] = list(data.get("c") or []) + ["Yapıştırma"]
        data["added"] = int(data.get("added") or 0) + 1
        for k, row in enumerate(data["rows"]):
            row.append(cell if k == 0 else {"t": "", "k": ""})

    def dv01_hedge(self, user: Optional[str], lang: Optional[str] = None) -> Dict[str, Any]:
        """DV01 Risk's "Hedge'i işle" (the desk, 28.11.2026: A3): the hedge recommender's suggestion of ``user``'s own
        position as Günlük İşlemler's OIS paste (``varrisk.hedge_paste``) - the text the dialog opens with.  Nothing is
        priced or saved here."""
        user = self.require_user(user)
        return self.et.call(self._dv01_hedge, user, lang or self.settings.locale)

    def _dv01_hedge(self, user: str, lang: str) -> Dict[str, Any]:
        from . import varrisk as vr
        book = self._book("tto")
        if "DV01_RISK" not in book.model.sheet_index:
            raise ServiceError("DV01 Risk sayfası yok", 404)
        calc = self._calc(user, book)
        si = book.model.sheet_index["DV01_RISK"]

        def get(addr: str) -> Any:
            return calc.get(si, *divmod(parse_a1(addr), COLS))

        rows = [{"name": get("B%d" % r), "active": get("C%d" % r), "start": get("D%d" % r), "end": get("E%d" % r),
                 "f": get("F%d" % r), "g": get("G%d" % r), "rate": get("J%d" % r), "dv01": get("K%d" % r),
                 "side": get("L%d" % r), "nominal": get("N%d" % r)} for r in range(ex.HEDGE_FIRST, ex.HEDGE_LAST + 1)]
        return vr.hedge_paste(rows, get("I3"), lang)

    # ================================================================== TRY rates two ways: bootstrap and PPK steps
    #: how many states of calculations the curves are kept for (a user's, a copy's)
    TRY_CURVES_KEPT = 16

    def _try_curves(self, book, calc: Calc) -> Optional[Dict[str, Any]]:
        """The TRY workbook's curves both ways out of ``calc`` (a user's calculation, a copy's layer:
        :func:`tto.ppkcurve.read`) - the bootstrap as it is, the PPK step curve and its offshore twin calibrated to the
        quotes; and ``off_boot``, the offshore curve as it is (its names' nodes, ln DF linear in days).  The Bootstrap side
        is the true bootstrap whatever the user's curve setting (interp.py: read through ``calc`` with the curve on
        Bootstrap - on PPK Motor's nodes are PPK's).  Made once for a state of the calculation and kept; what making them
        read counts as read by whatever is being made out of them (``calc.track`` - a page's panel: made again when any of
        it changes), a kept one's too.  ``None`` for a workbook without them."""
        idx = book.model.sheet_index
        if not all(s in idx for s in ("Motor", "OIS_MAIN", "Forward")):
            return None
        interp = getattr(self, "interp", None)
        base = interp.boot_of(book, calc) if interp is not None else calc
        cp = getattr(self, "curvepoints", None)
        points = cp.specs() if cp is not None else None          # (the desk's list: a curve that differs is built on it)
        state, level = [book.id, calc.engine.layout, book.engine.input_changes, cp.rev if cp is not None else 0], base
        while level is not None:                        # (the calculation and those below it: a change in any)
            state += [level.serial, level.epoch]
            level = level.parent
        kept = self.__dict__.setdefault("_try_curves_kept", {})
        hit = kept.get(base.serial)
        if hit is not None and hit[0] == state:
            if calc.track is not None:
                calc.track |= hit[2]
            return hit[1]
        outer, base.track = base.track, 0
        try:
            curves = pk.read(lambda sheet, r, c: base.get(idx[sheet], r, c), points)
            try:
                curves["off_boot"] = pk.LogLinear(bsp._named(book, base, "OFF_GUN") or [], bsp._named(book, base, "OFF_LNDF") or [])
            except ValueError:
                curves["off_boot"] = None
            mask = base.track
        finally:
            base.track = None if outer is None else outer | (base.track or 0)
        if base is not calc and calc.track is not None:
            calc.track |= mask
        kept.pop(base.serial, None)
        kept[base.serial] = (state, curves, mask)
        while len(kept) > self.TRY_CURVES_KEPT:
            kept.pop(next(iter(kept)))
        return curves

    # ================================================================== ASW against FX swaps
    def _asw_fx_calc(self, book, user: Optional[str]) -> Tuple[Optional[Calc], int]:
        """The ASW sheet's calculation on the FX swap implied curve, over the user's own inputs: every tenor with an FX
        rate in EK_FX (D6:D21) gets, in the place of the OIS quote its curve is built from (ASW!C65:R65), the par quote
        of the sheet's own convention that gives the discount factor the rate gives by its own convention there
        (``aswfx.to_sheet``: up to 9M FX swap implied, one period simple ACT/360; from 1Y XCCY - 1Y TRYSAQ1 -, annual
        ACT/360 par - as the desk's workbook reads them; 18M the discount factor of the offshore XCCY curve there, on the
        user's own curve setting - :meth:`_asw_fx_18m` -, its XCCY par given to EK_FX!D12); a tenor without one keeps its
        OIS quote, one whose rate gives no such quote is #N/A (the curve stops there, as the sheet's does at a missing
        quote).  The sheet's formulas are its own - for every user: this calculation takes the user's typed inputs only,
        not the values worked out for them (``engine.derived``: the PPK basamak mirror of EK_INTERP), so its curve between
        the nodes is the sheet's own whatever the user's interpolation setting; only the 18M point follows that setting
        (docs/curves.md).  ``None`` when no tenor has an FX rate; with the number that have one.  Made once
        for what a page shows at a time (the table's ASW FX column, its chart and EK_FX's FX zero rates read the same one;
        anything changed since - the 18M point too: made again)."""
        si, fi = book.model.sheet_index["ASW"], book.model.sheet_index[ex.FXC_SHEET]
        base = self._calc(user, book)
        shared = book.engine.shared
        x18 = self._asw_fx_18m(book, user, base)
        key = (user, book.id, id(base), base.epoch, shared.epoch, book.engine.input_changes, x18["point"], x18["label"])
        hit = getattr(self, "_fx_calc_kept", None)
        if hit is not None and hit[0] == key:
            return hit[1], hit[2]
        n = len(aswfx.TENORS)
        fx = [base.get(fi, ex.FXC_FIRST + k, col_to_index("D")) for k in range(n)]
        ois = [base.get(si, aswfx.ROW, aswfx.QUOTE_COL + k) for k in range(n)]
        days = [base.get(si, aswfx.ROW, aswfx.DAY_COL + i) for i in range(len(aswfx.NODES))]
        ov = dict(self._overlay(user, book)) if user else {}
        if user:
            # a row priced by a typed ASW (or dirty price: the table is two-way) is priced here at the clean price the
            # user's calculation has - its ASW on this curve worked out, not held at the level typed on the OIS curve
            pins, stores = self._twoway_pins(book, base, "ASW", ov)
            for cell in stores:
                ov.pop(cell, None)
            ov.update(pins)
        swapped = 0
        point = x18["point"]
        for k, t in enumerate(aswfx.to_sheet(ois, fx, days, {aswfx.CURVE_TENOR: point} if point is not None else None)):
            if t.kind != aswfx.OIS:
                ov[(si, aswfx.ROW * COLS + aswfx.QUOTE_COL + k)] = t.par if t.par is not None else XlError("#N/A")
                swapped += 1
        if point is not None:
            ov[(fi, ex.FXC_CURVE_ROW * COLS + col_to_index("D"))] = point.par     # (EK_FX's 18M: the FX quotes' line)
        calc = Calc(book.engine, shared, ov) if swapped else None
        self._fx_calc_kept = (key, calc, swapped, x18)
        return calc, swapped

    def _twoway_pins(self, book, base: Calc, sheet: str, overlay: Dict[Tuple[int, int], Any]
                     ) -> Tuple[Dict[Tuple[int, int], Any], List[Tuple[int, int]]]:
        """The rows of ``sheet``'s two-way tables (twoway.py) that a stored member prices for the user (``overlay``: their
        own values) - a typed ASW is a clean price on the curve it was typed on: ``(pins, stores)``, the in-place
        member's cell (the clean price) as ``base``, the user's calculation, has it, and those row-sides' stores.  A
        calculation of the sheet on another curve (ASW FX, the offshore history) takes the pins - and leaves the stores
        out where it can -, so it prices those rows at the user's price."""
        pins: Dict[Tuple[int, int], Any] = {}
        stores: List[Tuple[int, int]] = []
        for g in self.twoway.groups.values():
            own = next((m for m in g.members if m.own), None)
            if g.book is not book or g.sheet != sheet or own is None:
                continue
            for pos, cell in enumerate(own.cells):
                a = g.anchor(pos, overlay, book.engine.input_value)
                if a is None or a.own:
                    continue
                pins[cell] = base.get(cell[0], *divmod(cell[1], COLS))
                stores.extend(g.stores(pos))
        return pins, stores

    def _asw_fx_point(self, book, user: Optional[str]) -> Dict[str, Any]:
        """The 18M point the user's calculation on the FX swap curve was made with (:meth:`_asw_fx_18m`)."""
        self._asw_fx_calc(book, user)
        kept = getattr(self, "_fx_calc_kept", None)
        if kept is None or len(kept) < 4:
            return self._asw_fx_18m(book, user, self._calc(user, book))
        return kept[3]

    def _asw_fx_18m(self, book, user: Optional[str], base: Calc) -> Dict[str, Any]:
        """EK_FX's 18M - computed, never a quote (the desk, 18.11.2026: "TRYI18M gerçek bir kotasyon değil. Orada annual
        payment olduğu için 1Y'den sonra XCCY trade ediyor. Zero'yu oradan bulmamız gerekli. Bunun da interpolasyonu PPK'yı
        seçersem PPK'ya gelmeli"; "18M hesaplanacak"): ``aswfx.point_18m`` - the offshore TRY curve's discount factor at
        the ASW sheet's 18M node day, between its 1Y and 2Y XCCY nodes (TRYSAQ1, TRYSAQ2), with its 18M XCCY par (annual
        ACT/360, the coupons counted back from the maturity: 6M, then 12M - the ASW sheet's 6M node day) and zero rate.
        The curve is the user's own setting (Ayarlar → Eğri interpolasyonu): **Bootstrap** - the desk's offshore curve as
        the Forward sheet builds it (OFF_GUN / OFF_LNDF, read with the curve on Bootstrap: ln DF linear between its
        nodes); **PPK basamak** - ppkcurve's offshore PPK curve (:meth:`_try_curves`' ``off_ppk``; one that cannot be made:
        Bootstrap, said in the label) - out of the user's TRY workbook calculation (their own inputs count), seen from the
        ASW sheet's spot (ASW!T65; the curve's days are from the FX spot, Forward!I2).  Without both XCCY quotes no point:
        18M keeps its OIS quote, as a tenor without an FX price.

        Returns ``{"point": aswfx.Point | None, "mode": "boot" | "ppk", "label": EK_FX's words for it, "why": why there is
        none}``."""
        from .interp import BOOT, PPK
        mode = self.interp.mode(user) if getattr(self, "interp", None) is not None else BOOT
        out: Dict[str, Any] = {"point": None, "mode": mode, "label": aswfx.CURVE_LABEL % "Bootstrap", "why": ""}
        tto = self.books.get("tto")
        if tto is None or not all(s in tto.model.sheet_index for s in ("Forward", "Motor", "OIS_MAIN")):
            out["why"] = "TRY çalışma kitabının offshore eğrisi yok"
            return out
        si = book.model.sheet_index["ASW"]
        day = {m: base.get(si, aswfx.ROW, aswfx.DAY_COL + aswfx.node_of(m)) for m in aswfx.xccy_months(aswfx.CURVE_TENOR)}
        spot = base.get(si, aswfx.ROW, col_to_index("T"))
        tcalc = self._calc(user, tto)
        idx = tto.model.sheet_index

        def get(sheet: str, r: int, c: int) -> Any:
            return tcalc.get(idx[sheet], r, c)

        first = pk.XCCY_ROWS[0]
        xccy = pk.offshore_quotes([], [(get("Forward", r, pk.XCCY_LABEL), get("Forward", r, pk.XCCY_DAY),
                                        get("Forward", r, pk.XCCY_RATE)) for r in (first, first + 1)])
        if len(xccy) < len(aswfx.CURVE_NODES):
            out["why"] = "XCCY 1Y / 2Y (TRYSAQ1 / TRYSAQ2) fiyatı yok"
            return out
        fx_spot = to_num(get(*pk.FX_SPOT))
        curve = None
        if mode == PPK:
            curve = (self._try_curves(tto, tcalc) or {}).get("off_ppk")
            if curve is not None:
                out["label"] = aswfx.CURVE_LABEL % ex.INTERP_PPK
            else:
                out["label"] = aswfx.CURVE_LABEL % "Bootstrap - PPK basamak kurulamadı"
        if curve is None:
            boot = self.interp.boot_of(tto, tcalc) if getattr(self, "interp", None) is not None else tcalc
            try:
                curve = pk.LogLinear(bsp._named(tto, boot, "OFF_GUN") or [], bsp._named(tto, boot, "OFF_LNDF") or [])
            except ValueError:
                out["why"] = "offshore eğri kurulamadı (OFF_GUN / OFF_LNDF)"
                return out
        if type(spot) is not float or type(fx_spot) not in (float, int):
            out["why"] = "spot tarihi yok (ASW!T65 / Forward!I2)"
            return out
        out["point"] = aswfx.point_18m(curve, day[6], day[aswfx.CURVE_TENOR], spot - float(fx_spot))
        if out["point"] is None:
            out["why"] = "eğriden 18A okunamadı"
        return out

    @staticmethod
    def _chart_as(spec: Dict[str, Any], how: Dict[str, Any]) -> Dict[str, Any]:
        """A chart of the workbook under another title, value axis title and series names (a panel's ``as``)."""
        out = dict(spec)
        if how.get("title"):
            out["title"] = how["title"]
        if how.get("y_title"):
            out["axis_titles"] = [how["y_title"] if t == spec.get("y_title") else t for t in spec.get("axis_titles") or []]
            out["y_title"] = how["y_title"]
        names = how.get("names") or []
        out["series"] = [dict(s, name=names[i], name_ref=None) if i < len(names) and names[i] else s
                         for i, s in enumerate(spec.get("series") or [])]
        return out

    @staticmethod
    def _fx_series(fx: Optional[Calc], R: Renderer, spec: Dict[str, Any], data: Dict[str, Any], loc) -> None:
        """The series of a chart marked ``"curve": "fx"`` drawn on the FX swap implied curve: the same cells in the
        dashboard's calculation on it (``fx``, :meth:`_asw_fx_calc`; EK_FX's zero-coupon rates - the OIS curve's in the
        sheet - are then the FX curve's, the very discount factors the ASW FX column prices with).  Without it (no FX
        rate): no values."""
        picked = [k for k, s in enumerate(spec.get("series") or []) if s.get("curve") == "fx"]
        n = len(data.get("cats") or [])
        got = R.chart(fx, dict(spec, series=[spec["series"][k] for k in picked]), loc)["series"] if fx is not None else []
        for j, k in enumerate(picked):
            values = got[j]["data"] if j < len(got) else []
            data["series"][k]["data"] = (list(values) + [None] * n)[:n]

    def _fx_curve_columns(self, book, calc: Optional[Calc], data: Dict[str, Any], loc,
                          x18: Optional[Dict[str, Any]] = None) -> None:
        """EK_FX's tenors on the FX swap implied curve, next to the sheet's own columns: the curve's zero-coupon rate (EK_FX's
        OIS zero-coupon cell, K, in ``calc``, the calculation on the FX swap curve - :meth:`_asw_fx_calc`) and what the ASW
        sheet's curve is given there (ASW!C65:R65 in it: the FX rate as the par quote of the sheet's convention with the
        same discount factor, the OIS quote where there is no FX rate).  Without ``calc`` (no FX rate): empty.  ``x18``: the
        user's 18M point (:meth:`_asw_fx_point`) - its row as they have it (:meth:`_fx_curve_row`)."""
        if ex.FXC_SHEET not in book.model.sheet_index or "ASW" not in book.model.sheet_index:
            return
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows:
            return
        si, fi = book.model.sheet_index["ASW"], book.model.sheet_index[ex.FXC_SHEET]
        first, last = ex.FXC_FIRST, ex.FXC_FIRST + len(aswfx.TENORS) - 1
        zero = col_to_index(ex.FXC_ZERO_COL)

        def pct(v: Any) -> Dict[str, Any]:
            return {"t": numfmt.format_value(v, "0.000", loc), "v": v, "k": "n"} if type(v) is float else {"t": "", "k": ""}

        for i, r in enumerate(rnums):
            if r == first - 1:
                rows[i].extend([{"t": "FX sıfır kupon (%)", "k": "s", "b": 1, "f": "hd",
                                 "tip": "%s'nin vadedeki sıfır kupon faizi (yıllık bileşik, ACT/365: DF^(−365/gün) − 1): ASW FX hesabının "
                                        "kâğıtları iskonto ettiği eğri. %s; fiyatı olmayan vadede eğri o vadenin OIS kotasıyla sürer"
                                        % (self.ASW_FX_CURVE, self.FX_RATES_READ)},
                                {"t": "ASW'ye giden par (%)", "k": "s", "b": 1, "f": "hd",
                                 "tip": "ASW sayfasının eğrisinin FX tarafta bu vadede kurulduğu kota (ASW!C65:R65 yerine): FX faizi, sayfanın "
                                        "kuralında (3 aya kadar tek dönem basit ACT/365, sonra çeyreklik ACT/365 par) vadesinde aynı iskonto "
                                        "faktörünü veren par faiz; fiyatı olmayan vadede OIS kotası"}])
            elif first <= r <= last and calc is not None:
                rows[i].extend([pct(calc.get(fi, r, zero)), pct(calc.get(si, aswfx.ROW, aswfx.QUOTE_COL + r - first))])
            else:
                rows[i].extend([{"t": "", "k": ""}, {"t": "", "k": ""}])
        if x18 is not None and ex.FXC_CURVE_ROW in rnums:
            self._fx_curve_row(rows[rnums.index(ex.FXC_CURVE_ROW)], data.get("c") or [], x18, loc)
        data["c"] = list(data.get("c") or []) + ["FX sıfır", "ASW par"]
        data["added"] = int(data.get("added") or 0) + 2

    @staticmethod
    def _fx_curve_row(row: List[Dict[str, Any]], cols: Sequence[str], x18: Dict[str, Any], loc) -> None:
        """EK_FX's 18M row as the user has it (:meth:`_asw_fx_18m`): where it comes from - "hesaplanan (XCCY 1Y–2Y,
        Bootstrap)" or "… PPK basamak", their own curve setting -, the computed 18M XCCY par (D; in the workbook itself
        #N/A: it is no quote), its difference to OIS (F) and how it is read (I); its zero rate is the FX zero-coupon column's.
        Without the point: no price (OIS), and why."""
        at = {c: j for j, c in enumerate(cols)}
        p = x18.get("point")
        how = ("18A kota değil, hesaplanır: offshore eğrinin XCCY 1Y (TRYSAQ1) ile 2Y (TRYSAQ2) arasında 18A'daki iskonto "
               "faktörü, Ayarlar'daki eğri interpolasyonunuzla (Bootstrap: Forward'daki offshore eğri, ln DF günlere göre doğrusal; "
               "PPK basamak: offshore PPK eğrisi); faizi aynı eğride 18A XCCY par - yıllık ACT/360, kuponlar vadeden geriye: 6A, "
               "sonra 12A")
        cells: Dict[str, Dict[str, Any]] = {"B": {"t": "hesaplanan", "k": "s", "al": "c", "tip": how}}
        if p is not None:
            ois = row[at["E"]].get("v") if "E" in at and at["E"] < len(row) else None
            cells["C"] = {"t": x18["label"], "k": "s", "tip": how}
            cells["D"] = {"t": numfmt.format_value(p.par, "0.000", loc), "v": p.par, "k": "n", "b": 1,
                          "tip": "18A XCCY par (yıllık ACT/360, 6A + 12A): %s · iskonto faktörü %s · sıfır kupon %s%%"
                                 % (x18["label"], numfmt.format_value(p.df, "0.000000", loc),
                                    numfmt.format_value(p.zero, "0.000", loc))}
            diff = (p.par - ois) * 100 if type(ois) is float else None
            cells["F"] = {"t": numfmt.format_value(diff, "0.0", loc), "v": diff, "k": "n"} if diff is not None else {"t": "", "k": ""}
            cells["I"] = {"t": aswfx.RULES[aswfx.CURVE], "k": "s", "tip": how}
        else:
            cells["C"] = {"t": "yok", "k": "s", "tip": x18.get("why") or ""}
            cells["I"] = {"t": aswfx.RULES[aswfx.OIS], "k": "s",
                          "tip": "18A hesaplanamadı (%s): OIS kotası kalır" % (x18.get("why") or "eğri yok")}
        for c, cell in cells.items():
            j = at.get(c)
            if j is not None and j < len(row):
                row[j] = cell

    def _asw_fx_columns(self, book, user: Optional[str], data: Dict[str, Any], loc) -> None:
        """ASW against the FX swap implied curve next to ASW against OIS: the sheet's own calculation with the OIS quotes
        it builds its curve from (ASW!C65:R65) swapped for EK_FX's rates, each read by its own convention and given as
        the par quote of the sheet's convention with the same discount factor (:meth:`_asw_fx_calc`) - a tenor without
        one keeps its OIS quote.  Two columns on the right of the table: ASW FX and FX − OIS, in bp."""
        if ex.FXC_SHEET not in book.model.sheet_index or "ASW" not in book.model.sheet_index:
            return
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows:
            return
        si = book.model.sheet_index["ASW"]
        base = self._calc(user, book)
        calc, swapped = self._asw_fx_calc(book, user)
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
                rows[i].extend([{"t": "ASW FX ima (bp)", "k": "s", "b": 1, "f": "hd",
                                 "tip": "%s'ne göre ASW (EK_FX: %d / %d vade fiyatlı; %s). DİBS RV'nin ASW FX'i başka bir eğri: %s"
                                        % (self.ASW_FX_CURVE, swapped, len(ex.FXC_ROOTS), self.FX_RATES_READ, self.RV_FX_CURVE)},
                                {"t": "FX ima − OIS (bp)", "k": "s", "b": 1, "f": "hd",
                                 "tip": "ASW FX ima − ASW OIS (%s; OIS)" % self.ASW_FX_CURVE}])
            elif 7 <= r <= 56 and calc is not None:
                ois, fx = base.get(si, r, r_col), calc.get(si, r, r_col)
                rows[i].extend([bp(fx), bp(fx - ois if type(fx) is float and type(ois) is float else None, True)])
            else:
                rows[i].extend([{"t": "", "k": ""}, {"t": "", "k": ""}])
        data["c"] = list(data.get("c") or []) + ["ASW FX", "FX−OIS"]
        data["added"] = int(data.get("added") or 0) + 2

    # ================================================================== the ASW history against the offshore curve
    #: a calculation's ASW history on the offshore curve, a layer over it: ``(user, HIST_FX)`` - ``""`` everybody's
    HIST_FX = "asw-hist-fx"
    #: past days kept worked out on the offshore curve (aswfx.history_row: a page read finds them again)
    HIST_ROWS_KEPT = 4000

    def _asw_hist_fx(self, book, user: Optional[str]) -> Tuple[Optional[Calc], Dict[str, Any]]:
        """The ASW sheet's history on the offshore curve - the desk's "ASW geçmişini offshore'a göre de çiz": the
        sheet's own formulas, every past day's OIS quotes (``ASW!C66:R325``, its Bloomberg history blocks) swapped for
        that day's offshore rates as today's are for the "ASW FX" column (:meth:`_asw_fx_calc`): the dashboard's own
        daily closes (no Bloomberg request), each tenor's series by ``aswfx.history_series`` (TRYI 1–9M FX swap
        implied, TRYSAQ 1Y and 2–10Y XCCY; ICPL, then BGN; 18M computed from that day's TRYSAQ1 and TRYSAQ2 closes -
        Bootstrap: a past day has no PPK curve, ``aswfx.history_point``), each read by its own convention and given as
        the par quote of the sheet's convention with the same discount factor; a tenor without one (a day without its
        close) keeps that day's OIS quote.  A day without any offshore close has no offshore ASW at all (``info["none"]``: the
        page leaves its point and its cells empty) - as today's ASW FX has none without an FX rate.  Today's row (65)
        is the ASW FX column's: its quotes as :meth:`_asw_fx_calc` has them.  The blocks are given as a whole (an array
        for each block's formula, ``aswfx.history_anchors`` - an engine input), in a layer on top of the user's
        calculation: only what follows the swapped quotes is computed there, and it is kept while the market moves
        (today's row follows it).

        Returns ``(calc, info)``: ``info["n"]`` / ``["kinds"]`` / ``["day"]`` the tenors offshore on each past row (row
        -> count / each tenor's kind / its day), ``["days"]`` the past days, ``["offshore"]`` those with an offshore
        rate, ``["today"]`` the tenors priced in EK_FX now, ``["none"]`` the rows without any (today's: 65).
        ``(None, info)`` when the workbook has no such history."""
        info: Dict[str, Any] = {"n": {}, "kinds": {}, "day": {}, "days": 0, "offshore": 0, "today": 0, "none": set()}
        if "ASW" not in book.model.sheet_index or ex.FXC_SHEET not in book.model.sheet_index \
                or any(x.startswith(ex.ASW_HIST_NAME + ":") for x in getattr(book, "left_out", ())):
            return None, info
        si = book.model.sheet_index["ASW"]
        eng = book.engine
        base = self._calc(user, book)
        pick = (si, parse_a1(ex.ASW_HIST_PICK))
        if base is not eng.shared and all(cell == pick for cell in self._overlay(user, book)):
            base = eng.shared             # (the chart's choice alone - read by no formula: everybody's history is theirs)
        who = (user or "") if base is not eng.shared else ""
        fx, swapped = self._asw_fx_calc(book, user)
        q0, q1 = aswfx.ROW * COLS + aswfx.QUOTE_COL, aswfx.ROW * COLS + aswfx.QUOTE_COL + len(aswfx.TENORS)
        ov = {cell: v for cell, v in (fx.overlay.items() if fx is not None else ()) if cell[0] == si and q0 <= cell[1] < q1}
        arrays, rows = self._asw_hist_arrays(book, base, who)
        ov.update(arrays)
        if base is not eng.shared:
            ov.update(self.interp.boot_cells(book))    # (a PPK user's own: the offshore curve bootstrapped, as the desk's)
            # (today's row reads the table's clean prices: a row priced by a typed ASW at the user's price, as ASW FX)
            ov.update(self._twoway_pins(book, base, "ASW", self._overlay(user, book))[0])
        info.update(rows)
        info["today"] = swapped
        info["none"] = {r for r, k in rows["n"].items() if not k} | (set() if swapped else {aswfx.ROW})
        return eng.layer((who, self.HIST_FX), base, ov), info

    def _asw_hist_arrays(self, book, base: Calc, who: str) -> Tuple[Dict[Tuple[int, int], Any], Dict[str, Any]]:
        """The ASW history's Bloomberg blocks with the offshore quotes in place, by their formulas' cells: each block as
        ``base`` (the user's calculation) has it, every past day with an offshore rate given the par quotes
        (``aswfx.history_row``; one no quote reaches: #N/A - the curve stops there, as the sheet's does at a missing
        quote; 18M computed from that day's TRYSAQ1 and TRYSAQ2 closes, ``aswfx.history_pair``); a block with nothing
        swapped is not given.  Worked out again only when what it read changed (the blocks, the days of the curve's nodes -
        the masks of what ``base`` gave - and the history's closes and series); a block that comes out the same is the same
        array (nothing is computed again for it)."""
        si = book.model.sheet_index["ASW"]
        defs = self.history.snapshot()["defs"]
        series, pair = aswfx.history_series(defs), aswfx.history_pair(defs)
        mark = (getattr(self.history, "rev", 0), tuple(s.ids() if s is not None else None for s in series),
                tuple(s.ids() for s in pair) if pair is not None else None)
        kept = self._hist_fx_kept.get(who)
        if kept is not None and kept["mark"] == mark and self._still(kept["meta"], base):
            return kept["arrays"], kept["info"]
        saved, base.track = base.track, 0                 # (the masks of what is read: when to work it out again)
        try:
            arrays, info = self._asw_hist_build(book, base, si, series, pair, kept["arrays"] if kept is not None else {})
        finally:
            mask = base.track or 0
            base.track = None if saved is None else saved | mask
        self._hist_fx_kept[who] = {"mark": mark, "meta": (base.serial, base.engine.layout, base.epoch, mask),
                                   "arrays": arrays, "info": info}
        return arrays, info

    def _asw_hist_build(self, book, base: Calc, si: int, series: Sequence[Any], pair: Optional[Tuple[Any, Any]],
                        before: Dict[Tuple[int, int], Any]) -> Tuple[Dict[Tuple[int, int], Any], Dict[str, Any]]:
        n, nodes = len(aswfx.TENORS), len(aswfx.NODES)
        get = base.get
        days = [(r, d) for r, d in ((r, get(si, r, aswfx.HIST_DATE_COL)) for r in range(aswfx.HIST_FIRST, aswfx.HIST_LAST + 1))
                if type(d) is float and 20000 < d < 80000]
        info: Dict[str, Any] = {"n": {}, "kinds": {}, "day": dict(days), "days": len(days), "offshore": 0}
        if not days:
            return {}, info
        lo, hi = (serial_to_date(x).isoformat() for x in (min(d for _, d in days), max(d for _, d in days)))
        ids = sorted({i for s in list(series) + list(pair or ()) if s is not None for i in s.ids()})
        data = self.store.hist_many(ids, lo, hi) if ids else {}
        closes = [s.merged(data)[1] if s is not None else {} for s in series]
        xccy = [s.merged(data)[1] for s in pair] if pair is not None else None       # (TRYSAQ1, TRYSAQ2: 18M)
        swap: Dict[int, List[Any]] = {}                   # row -> what each tenor's cell is given (None: its own)
        for r, d in days:
            day = serial_to_date(d).isoformat()
            fx = [c.get(day) for c in closes]
            two = tuple(c.get(day) for c in xccy) if xccy is not None else ()
            two = two if len(two) == 2 and None not in two else None
            kinds = [aswfx.OIS] * n
            if any(x is not None for x in fx) or two is not None:
                pars, kinds = self._asw_hist_row([get(si, r, aswfx.QUOTE_COL + k) for k in range(n)], fx,
                                                 [get(si, r, aswfx.DAY_COL + i) for i in range(nodes)], two)
                swap[r] = [None if kind == aswfx.OIS else (p if p is not None else XlError("#N/A")) for p, kind in zip(pars, kinds)]
            info["kinds"][r] = kinds
            info["n"][r] = sum(1 for kind in kinds if kind != aswfx.OIS)
            info["offshore"] += 1 if info["n"][r] else 0
        arrays: Dict[Tuple[int, int], Any] = {}
        eng = book.engine
        for anchor in sorted({a for a in aswfx.history_anchors(book.model.sheets[si]) if a is not None}):
            ref = eng.arr[si].get(anchor)
            if ref is None:
                continue
            r1, c1, r2, c2 = ref
            rows = [[get(si, r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]
            while rows and all(x is None for x in rows[-1]):
                rows.pop()                                # (the block's own rows: below them its area is empty)
            changed = False
            for i, row in enumerate(rows):
                put = swap.get(r1 + i)
                if put is None:
                    continue
                for j in range(len(row)):
                    k = c1 + j - aswfx.QUOTE_COL
                    if 0 <= k < n and put[k] is not None:
                        row[j] = put[k]
                        changed = True
            if not changed:
                continue
            old = before.get((si, anchor))
            arrays[(si, anchor)] = old if old is not None and old.rows == rows else XlArray(rows)
        return arrays, info

    def _asw_hist_row(self, ois: List[Any], fx: List[Any], days: List[Any],
                      xccy: Optional[Tuple[Any, Any]] = None) -> Tuple[List[Optional[float]], List[str]]:
        """``aswfx.history_row``, kept: the same day is worked out once."""
        key = (tuple(x if type(x) is float else None for x in ois), tuple(fx), tuple(x if type(x) is float else None for x in days),
               xccy)
        hit = self._hist_fx_rows.get(key)
        if hit is None:
            if len(self._hist_fx_rows) >= self.HIST_ROWS_KEPT:
                self._hist_fx_rows.clear()
            hit = self._hist_fx_rows[key] = aswfx.history_row(ois, fx, days, xccy)
        return hit

    @staticmethod
    def _asw_hist_choice(book, calc) -> str:
        """What the user's ASW history chart is drawn against (``ASW!N3``: OIS, Offshore, İkisi; anything else OIS)."""
        r, c = divmod(parse_a1(ex.ASW_HIST_PICK), COLS)
        v = calc.get(book.model.sheet_index["ASW"], r, c) if "ASW" in book.model.sheet_index else None
        return v if isinstance(v, str) and v in ex.ASW_HIST_CHOICES else ex.ASW_HIST_CHOICES[0]

    def _asw_hist_chart(self, book, user: Optional[str], calc, R: Renderer, spec: Dict[str, Any], loc,
                        p: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
        """The ASW history's chart as the user chose it (:meth:`_asw_hist_choice`): against OIS - the workbook's chart,
        as before -, against the offshore curve (the same chart on :meth:`_asw_hist_fx`) or both (the offshore
        series dashed beside the OIS ones).  A day without any offshore close has no offshore point: a gap in the
        offshore line.  Returns the chart, the choice for the page's selector and a line on the offshore days for the
        note."""
        choices = ex.ASW_HIST_CHOICES
        choice = self._asw_hist_choice(book, calc)
        pick = {"ref": "ASW!%s" % (p.get("pick") or ex.ASW_HIST_PICK), "book": book.id, "value": choice,
                "options": list(choices), "default": choices[0]}
        ois = R.chart(calc, spec, loc)
        if choice == choices[0]:
            return ois, pick, ""
        fxh, info = self._asw_hist_fx(book, user)
        if fxh is None:
            return ois, pick, "Offshore eğrisine göre geçmiş bu dosyada kurulamadı: OIS'e göre çizildi."
        fx = R.chart(fxh, spec, loc)
        both = choice == choices[2]
        name = lambda s, k: s.get("name") or "Kâğıt %d" % (k + 1)            # noqa: E731
        # (the points by their day - the chart's x: a past row's, today's)
        gaps = {info["day"][r] if r != aswfx.ROW else calc.get(book.model.sheet_index["ASW"], r, aswfx.HIST_DATE_COL)
                for r in info["none"] if r == aswfx.ROW or r in info["day"]}
        for k, s in enumerate(fx["series"]):
            s["name"] = "%s · offshore" % name(s, k)
            if both:
                s["dash"] = 1
            if gaps and "x" in s:
                s["data"] = [None if x in gaps else v for x, v in zip(s["x"], s["data"])]
        if both:
            for k, s in enumerate(ois["series"]):
                s["name"] = "%s · OIS" % name(s, k)
            out = dict(ois, series=ois["series"] + fx["series"], title="ASW geçmişi · OIS ve offshore (son nokta canlı)")
        else:
            out = dict(fx, title="ASW geçmişi · offshore eğrisine göre (son nokta canlı)")
        if not info["days"]:
            line = "Offshore: geçmiş yok (Bloomberg geçmişi boş) - yalnız bugünkü nokta."
        else:
            line = ("Offshore faizli gün: %d / %d - offshore kapanışı olmayan gün çizilmez (gün gün kaç vade: geçmiş tablosu); "
                    "bugün EK_FX'te %d / %d vade fiyatlı." % (info["offshore"], info["days"], info["today"], len(aswfx.TENORS)))
        return out, pick, line

    @staticmethod
    def _tenor_label(months: int) -> str:
        return "%dM" % months if months % 12 else "%dY" % (months // 12)

    def _asw_hist_fx_columns(self, book, user: Optional[str], R: Renderer, data: Dict[str, Any], loc) -> None:
        """The ASW history table's ASWs on the offshore curve beside the OIS ones (:meth:`_asw_hist_fx`): ASW 1–3 on it,
        and how many of the curve's 16 tenors were offshore that day (which ones: the cell's tip; today's row: the
        tenors EK_FX prices now).  A day without any offshore close: no offshore ASW (empty), 0 / 16."""
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows or "ASW" not in book.model.sheet_index:
            return
        si = book.model.sheet_index["ASW"]
        fxh, info = self._asw_hist_fx(book, user)
        n = len(aswfx.TENORS)
        cols = [col_to_index(c) for c in "XYZ"]
        how = ("o günün offshore faizleriyle - panonun günlük geçmişinden: 1–9A TRYI FX swap ima, 1Y ve 2–10Y TRYSAQ XCCY; önce "
               "ICPL, yoksa BGN. %s. 18A o günün TRYSAQ1 ve TRYSAQ2 kapanışlarından hesaplanır: XCCY 1Y–2Y eğrisi, ln DF günlere "
               "göre doğrusal (Bootstrap - geçmiş günün PPK eğrisi yok: PPK basamak ayarında da geçmiş günler Bootstrap'la; "
               "bugünkü satır ayarınızla). O gün kapanışı olmayan vade (18A: iki kapanıştan biri) o günün OIS kotasıyla; o gün "
               "hiç offshore kapanış yoksa boş. Son satır canlı: ASW tablosunun ASW FX ima değeri (%s)"
               % (self.FX_RATES_READ, self.ASW_FX_CURVE))
        head = [{"t": "ASW %d offshore" % (k + 1), "k": "s", "b": 1, "f": "hd",
                 "tip": "Kâğıt %d · ASW, offshore eğrisine göre: sayfanın kendi hesabı, OIS kotaları yerine %s" % (k + 1, how)}
                for k in range(3)]
        head.append({"t": "Offshore vade", "k": "s", "b": 1, "f": "hd",
                     "tip": "O gün eğrinin %d vadesinden kaçı offshore faizden (üzerine gelince hangileri); kalanı o günün OIS "
                            "kotasıyla. Bugün: EK_FX'te fiyatı olan vadeler" % n})
        empty = {"t": "", "k": ""}
        labels = [self._tenor_label(m) for m in aswfx.TENORS]
        for i, r in enumerate(rnums):
            if r == aswfx.ROW - 1:
                rows[i].extend([dict(c) for c in head])
                continue
            if fxh is None or not (r == aswfx.ROW or r in info["n"]):
                rows[i].extend([dict(empty) for _ in range(4)])
                continue
            if r in info["none"]:
                # no offshore close that day (today: no FX rate in EK_FX - the ASW FX column is empty too): no offshore ASW
                rows[i].extend([dict(empty) for _ in cols] + [{
                    "t": "0 / %d" % n, "k": "s", "al": "c", "cls": "soft",
                    "tip": "o gün offshore kapanışı yok" if r != aswfx.ROW else "bugün EK_FX'te FX faizi yok"}])
                continue
            cells = [R.cell(fxh, si, r, c, loc) for c in cols]
            if r == aswfx.ROW:
                count = {"t": "%d / %d" % (info["today"], n), "k": "s", "al": "c",
                         "tip": "Bugün: EK_FX'te %d / %d vade fiyatlı (ASW FX ima'nın eğrisi)" % (info["today"], n)}
            else:
                kinds = info["kinds"].get(r) or []
                off = [labels[k] for k, kind in enumerate(kinds) if kind != aswfx.OIS]
                own = [labels[k] for k, kind in enumerate(kinds) if kind == aswfx.OIS]
                count = {"t": "%d / %d" % (info["n"][r], n), "k": "s", "al": "c",
                         "tip": "Offshore: %s · OIS: %s" % (" ".join(off), " ".join(own) or "yok")}
            rows[i].extend(cells + [count])
        data["c"] = list(data.get("c") or []) + ["ASW 1 off", "ASW 2 off", "ASW 3 off", "Off vade"]
        data["added"] = int(data.get("added") or 0) + 4

    #: OIS · PPK's FRA lists (OIS_MAIN): the whole list - its header row, its rows - and the 15 best (by their label in it)
    FRA_ALL, FRA_ALL_HEAD, FRA_TOP, FRA_TOP_HEAD = (336, 438), 335, (66, 80), 65

    def _fra_bucket_columns(self, book, calc, data: Dict[str, Any], loc) -> None:
        """Where each FRA of OIS · PPK's lists goes in the desk's buckets, done in its YÖN at its Nominal as Günlük
        İşlemler books it: two columns, the start leg's and the end leg's - the bucket (a leg between buckets split between
        the two around it, linearly in months: "1Y −5.922 $ + 18M −5.922 $"; :func:`blotter.bucket_split`), the DV01 ($,
        + pay: the blotter's sign) and the leg's rate.  The whole list's own columns: the legs' rates (I, J), DV01s (K, L), months (M, N), YÖN (D); the
        15 best find their FRA there by its label."""
        if "OIS_MAIN" not in book.model.sheet_index:
            return
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows:
            return
        si = book.model.sheet_index["OIS_MAIN"]
        get = lambda r, col: calc.get(si, r, col_to_index(col))                       # noqa: E731
        legs: Dict[str, Tuple[int, ...]] = {}
        for r in range(self.FRA_ALL[0], self.FRA_ALL[1] + 1):
            label = get(r, "A")
            if isinstance(label, str) and label.strip() and label.strip() not in legs:
                legs[label.strip()] = (r,)
        dv_fmt, rate_fmt = "#,##0", "0.00"

        def leg_cell(months: Any, rate: Any, dv01: Any, sign: int, which: str, side: str) -> Dict[str, Any]:
            if type(months) is not float or months <= 0 or type(dv01) is not float or type(rate) is not float:
                return {"t": "", "k": ""}
            m = int(round(months))
            parts = bl.bucket_split(m)
            mark = {1: "+", -1: "−"}.get(sign, "")
            rate_t = numfmt.format_value(rate * 100.0, rate_fmt, loc)
            text = " + ".join("%s %s%s $" % (bl.month_label(b), mark, numfmt.format_value(abs(dv01) * w, dv_fmt, loc))
                              for b, w in parts) + " · %" + rate_t
            split = "" if len(parts) == 1 else " - %s'de işlem olmaz: iki yanındaki kovaya aylara göre bölünür (%s)" % (
                bl.month_label(m), ", ".join("%%%s %s" % (numfmt.format_value(w * 100.0, "0", loc), bl.month_label(b)) for b, w in parts))
            cell = {"t": text, "k": "s", "al": "r",
                    "tip": "%s bacağı (%s): %s · DV01 %s%s $ · oran %%%s%s" % (
                        which, bl.month_label(m), side or "yön yok", mark, numfmt.format_value(abs(dv01), dv_fmt, loc), rate_t, split)}
            if sign:
                cell["c"] = "pos" if sign > 0 else "neg"
            return cell

        head = [{"t": "Başlangıç bacağı → kova", "k": "s", "b": 1, "f": "hd",
                 "tip": "Bu FRA YÖN'deki yönde, Nominal'le yapılınca başlangıç bacağının masanın kovasına yazılan DV01'i ($; + pay, − "
                        "receive - Günlük İşlemler'in işareti) ve oranı. Kovalar arasındaki vade (15M, 21M, 27M …) iki yanındaki "
                        "kovaya aylara göre bölünür (15M: yarısı 1Y, yarısı 18M; 27M: ¾ 2Y, ¼ 3Y), Günlük İşlemler'deki gibi."},
                {"t": "Bitiş bacağı → kova", "k": "s", "b": 1, "f": "hd",
                 "tip": "Bitiş bacağının kovası, DV01'i ($; + pay, − receive) ve oranı - aynı kural. RECEIVE FRA: başlangıç pay, "
                        "bitiş receive; PAY FRA tersi; YÖN \"–\" ise işaret yok."}]
        for i, r in enumerate(rnums):
            if r in (self.FRA_ALL_HEAD, self.FRA_TOP_HEAD):
                rows[i].extend([dict(c) for c in head])
                continue
            src = None
            if self.FRA_ALL[0] <= r <= self.FRA_ALL[1]:
                src, yon = r, get(r, "D")
            elif self.FRA_TOP[0] <= r <= self.FRA_TOP[1]:
                label = get(r, "B")
                src = legs.get(label.strip())[0] if isinstance(label, str) and label.strip() in legs else None
                yon = get(r, "E")
            if src is None:
                rows[i].extend([{"t": "", "k": ""}, {"t": "", "k": ""}])
                continue
            rec = yon == "RECEIVE"
            sign = (1 if rec else -1) if yon in ("RECEIVE", "PAY") else 0          # the start leg: a RECEIVE FRA pays it
            start_side = ("PAY" if rec else "RECEIVE") if sign else ""
            end_side = ("RECEIVE" if rec else "PAY") if sign else ""
            rows[i].extend([leg_cell(get(src, "M"), get(src, "I"), get(src, "K"), sign, "Başlangıç", start_side),
                            leg_cell(get(src, "N"), get(src, "J"), get(src, "L"), -sign, "Bitiş", end_side)])
        data["c"] = list(data.get("c") or []) + ["Başl. kova", "Bitiş kova"]
        data["added"] = int(data.get("added") or 0) + 2

    # ------------------------------------------------------------------ the second view: PPK steps
    #: what the two ways are called on the pages
    BOOT_TIP = ("Bootstrap (Murex) = bugünkü eğri, Murex'in MTM'i: OIS kotalarının par faizleri aylara göre doğrusal, "
                "çeyreklik bootstrap, ln DF günlere göre doğrusal (Motor)")
    PPK_TIP = ("PPK basamak = TLREF toplantılar arasında sabit, kotalara aynen oturur: PPK çözücüsünün ima patikası "
               "(MPC ima) iki kotalı vade arasında sabit bir O/N kaydırmayla bütün OIS kotalarını kendi konvansiyonlarıyla "
               "(3 aya kadar tek dönem basit ACT/365, sonra çeyreklik par) aynen fiyatlar. Bootstrap'la kotalı vadelerde "
               "aynı, aralarında farklı")

    #: what the market of those lists is for a user on PPK basamak (Ayarlar → Eğri interpolasyonu): PPK's - the second
    #: view beside it is then the true Bootstrap (Murex)
    ON_PPK_TIP = ("Eğri ayarınız PPK basamak: piyasa sütunu PPK basamak - Motor'un düğümleri PPK eğrisinde, aralarında ln DF "
                  "günlere göre doğrusal (çeyreklik takvimdeki FRA'da tam PPK). Yanındaki sütun gerçek Bootstrap (Murex), fark "
                  "PPK − Bootstrap")
    ON_PPK_BOOT_TIP = ("Aynı satır gerçek Bootstrap (Murex) eğrisiyle - bugünkü eğri, Murex'in MTM'i: OIS kotalarının par "
                       "faizleri aylara göre doğrusal, çeyreklik bootstrap, ln DF günlere göre doğrusal (Motor; offshore'da FX swap "
                       "≤9M + XCCY 1Y–10Y). Eğri ayarınız PPK basamak olduğu için piyasa sütunu PPK basamak; bu sütun masanın / "
                       "Bootstrap'taki meslektaşlarınızın gördüğü değer")

    def _on_ppk(self, book, calc) -> bool:
        """Whether ``calc`` reads the TRY curves on PPK basamak (a user's choice, with the PPK curve there)."""
        interp = getattr(self, "interp", None)
        if interp is None or not interp.available or book is not interp.tto:
            return False
        si, rc = interp.status_cells["on"]
        return calc.get(si, *divmod(rc, COLS)) == 1.0

    @staticmethod
    def _shift_text(report: Optional[List[Dict[str, Any]]], loc, what: str = "O/N kaydırma") -> str:
        """A calibration in a line: the shift of each stretch (bp) and the most the shape missed a quote by."""
        if not report:
            return ""
        miss = max(report, key=lambda x: abs(x["miss_bp"]))
        return "%s (bp, kotalı vadeye kadar): %s. MPC ima'nın kotalardan kendi farkı en çok %s bp (%s)" % (
            what, " · ".join("%s %s" % (x["name"], numfmt.format_value(x["shift_bp"], "+0.0;-0.0;0.0", loc)) for x in report),
            numfmt.format_value(abs(miss["miss_bp"]), "0.0", loc), miss["name"])

    @staticmethod
    def _cell_format(book, si: int, r: int, c: int) -> str:
        st = book.model.sheets[si].styles.get(r * COLS + c, 0)
        return book.model.numfmts[st] if st < len(book.model.numfmts) else "General"

    @staticmethod
    def _diff_cell(v: float, fmt: str, loc) -> Dict[str, Any]:
        """A signed difference: + green, − red; one that rounds to 0 is a plain 0."""
        text = numfmt.format_value(v, fmt, loc)
        shown = any(ch in "123456789" for ch in text)
        cell = {"t": ("+" + text if v > 0 else text) if shown else numfmt.format_value(0.0, fmt, loc), "v": v, "k": "n"}
        if shown:
            cell["c"] = "pos" if v > 0 else "neg"
        return cell

    def _fra_ppk_columns(self, book, calc, data: Dict[str, Any], loc) -> None:
        """OIS · PPK's FRA lists both ways: next to the list's market (Bootstrap - today's curve, Murex's MTM) the FRA on
        the PPK step curve and the difference (bp) - each row's FRA (the whole list's months, M and N; the 15 best find
        theirs there by its label) on the quarterly calendar and day count the list's market uses (Motor's: OIS_MAIN!B336),
        so the difference is the curve's alone.  The market column's header says which way it is.  A user on PPK basamak
        (interp.py): the list's market is PPK's - beside it the true Bootstrap (Murex) then, the difference PPK − Bootstrap
        as for everybody."""
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows or "OIS_MAIN" not in book.model.sheet_index:
            return
        si = book.model.sheet_index["OIS_MAIN"]
        get = lambda r, col: calc.get(si, r, col_to_index(col))                       # noqa: E731
        cv = self._try_curves(book, calc) or {}
        ppk, grid = cv.get("ppk"), cv.get("grid")
        on_ppk = self._on_ppk(book, calc)
        other = cv.get("boot") if on_ppk else ppk          # (the second view: the way the market is not)
        months: Dict[str, Tuple[int, Any, Any]] = {}
        for r in range(self.FRA_ALL[0], self.FRA_ALL[1] + 1):
            label = get(r, "A")
            if isinstance(label, str) and label.strip() and label.strip() not in months:
                months[label.strip()] = (r, get(r, "M"), get(r, "N"))
        why = "" if ppk is not None else "; ".join(cv.get("errors") or []) or "PPK basamak eğrisi kurulamadı"
        if on_ppk:
            head = [{"t": "Bootstrap (Murex)", "k": "s", "b": 1, "f": "hd",
                     "tip": "%s.\nFRA, listenin piyasasıyla aynı tarihler ve gün sayımıyla (Motor'un çeyreklik takvimi, ACT/365): "
                            "fark yalnız eğriden." % self.ON_PPK_BOOT_TIP},
                    {"t": "PPK − Bootstrap (bp)", "k": "s", "b": 1, "f": "hd",
                     "tip": "Piyasa (PPK basamak: ayarınız) − Bootstrap (Murex), bp. İki yöntem kotalı vadelerde aynı; fark kotalı "
                            "iki vadenin arasındaki FRA'larda (12x15, 15x18 …) çıkar, kotalı vadeleri birleştirenlerde (12x18, "
                            "1Y1Y …) ~0.\n%s%s" % (self._shift_text(cv.get("report"), loc), ("\n" + why) if why else "")}]
        else:
            head = [{"t": "PPK basamak", "k": "s", "b": 1, "f": "hd",
                     "tip": "%s.\nFRA, listenin piyasasıyla aynı tarihler ve gün sayımıyla (Motor'un çeyreklik takvimi, ACT/365): "
                            "fark yalnız eğriden.\n%s%s" % (self.PPK_TIP, self._shift_text(cv.get("report"), loc),
                                                             ("\n" + why) if why else "")},
                    {"t": "PPK − piyasa (bp)", "k": "s", "b": 1, "f": "hd",
                     "tip": "PPK basamak − Piyasa (Bootstrap), bp. İki yöntem kotalı vadelerde aynı; fark kotalı iki vadenin "
                            "arasındaki FRA'larda (12x15, 15x18 …) çıkar, kotalı vadeleri birleştirenlerde (12x18, 1Y1Y …) ~0."}]
        market_col = {self.FRA_ALL_HEAD: "B", self.FRA_TOP_HEAD: "C"}
        letters = data.get("c") or []
        for i, r in enumerate(rnums):
            if r in market_col:
                col = market_col[r]
                if col in letters and isinstance(rows[i][letters.index(col)], dict):
                    cell = rows[i][letters.index(col)]
                    cell["tip"] = (cell["tip"] + "\n" if cell.get("tip") else "") + (self.ON_PPK_TIP if on_ppk else self.BOOT_TIP)
                rows[i].extend([dict(c) for c in head])
                continue
            src, mcol = None, None
            if self.FRA_ALL[0] <= r <= self.FRA_ALL[1]:
                src, mcol = (r, get(r, "M"), get(r, "N")), "B"
            elif self.FRA_TOP[0] <= r <= self.FRA_TOP[1]:
                label = get(r, "B")
                src, mcol = (months.get(label.strip()) if isinstance(label, str) else None), "C"
            value = None
            if src is not None and ppk is not None and other is not None and grid is not None \
                    and all(type(x) is float for x in src[1:]):
                value = pk.fra(other, grid, int(src[1]), int(src[2]))
            market = get(r, mcol) if mcol else None
            if value is None or type(market) is not float:
                rows[i].extend([{"t": "", "k": ""}, {"t": "", "k": ""}])
                continue
            fmt = self._cell_format(book, si, r, col_to_index(mcol))
            way_ppk, way_boot = (market, value) if on_ppk else (value, market)
            rows[i].extend([{"t": numfmt.format_value(value, fmt, loc), "v": value, "k": "n",
                             "tip": "PPK basamak: %s · Bootstrap: %s" % (numfmt.format_value(way_ppk, "0.000%", loc),
                                                                      numfmt.format_value(way_boot, "0.000%", loc))},
                            self._diff_cell((way_ppk - way_boot) * 10000.0, "0.0", loc)])
        data["c"] = list(letters) + (["Bootstrap", "PPK fark"] if on_ppk else ["PPK basamak", "PPK fark"])
        data["added"] = int(data.get("added") or 0) + 2

    #: MASA's broken-date block: the rows the PPK curves price, the format of their difference (the block's own "Fark":
    #: points for the forward rows, bp for the rates) and its scale
    BROKEN_DIFF = {pk.BROKEN_FWD: 10000.0, pk.BROKEN_POINTS: 1.0, pk.BROKEN_SIMPLE: 10000.0, pk.BROKEN_SIMPLE365: 10000.0,
                   pk.BROKEN_ON: 10000.0, pk.BROKEN_OIS: 10000.0, pk.BROKEN_XCCY: 10000.0}

    def _broken_ppk_columns(self, book, calc, data: Dict[str, Any], loc) -> None:
        """MASA's broken-date block (KIRIK VADE & KARŞILIK) both ways: next to its market (column F: the offshore curve,
        BOOT for OIS) the same rows on the PPK curves and the difference - the forward, simple and O/N rows and XCCY on the
        PPK-shaped offshore curve (MPC ima + a flat basis between the offshore quotes), OIS on the PPK step curve; with the
        block's own date, schedules and day counts (:func:`tto.ppkcurve.broken`), so the difference is the curve's alone.
        A row the block gives no market for gets none either.  A user on PPK basamak (interp.py): the block's market is
        PPK's - beside it the same rows on the true Bootstrap curves then, the difference PPK − Bootstrap as for everybody."""
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows or pk.BROKEN_SHEET not in book.model.sheet_index:
            return
        si = book.model.sheet_index[pk.BROKEN_SHEET]
        cv = self._try_curves(book, calc) or {}
        idx = book.model.sheet_index
        on_ppk = self._on_ppk(book, calc)
        if on_ppk:
            base = self.interp.boot_of(book, calc)
            got = pk.broken(lambda sheet, r, c: base.get(idx[sheet], r, c), cv.get("boot"), cv.get("off_boot")) if cv else {}
        else:
            got = pk.broken(lambda sheet, r, c: calc.get(idx[sheet], r, c), cv.get("ppk"), cv.get("off_ppk")) if cv else {}
        f_col, h_col = col_to_index("F"), col_to_index("H")
        why = "; ".join(cv.get("errors") or [])
        if on_ppk:
            head = [{"t": "Bootstrap (Murex)", "k": "s", "b": 1, "f": "hd",
                     "tip": "%s. Forward / basit / O/N / XCCY offshore eğriden (FX swap ≤9M + XCCY 1Y–10Y, ln DF doğrusal), OIS par "
                            "Motor'un Bootstrap düğümlerinden; tarih, kupon takvimi ve gün sayımı bloğun kendi (yardımcı "
                            "BK170:CC234): fark yalnız eğriden.%s" % (self.ON_PPK_BOOT_TIP, ("\n" + why) if why else "")},
                    {"t": "PPK − Bootstrap", "k": "s", "b": 1, "f": "hd",
                     "tip": "Piyasa (PPK basamak: ayarınız) − Bootstrap (Murex): forward satırlarında puan, oranlarda bp. Kotalı "
                            "vadede ~0 (iki eğri de kotaya oturur), kotaların arasında iki yöntemin farkı."}]
        else:
            head = [{"t": "PPK basamak", "k": "s", "b": 1, "f": "hd",
                     "tip": "Aynı satır PPK basamak eğrileriyle. Forward / basit / O/N ve XCCY: PPK biçimli offshore eğri - MPC ima "
                            "patikası, offshore kotalar (FX swap ima ≤9M, XCCY 1Y–10Y) arasında sabit bir bazla bu kotalara kendi "
                            "konvansiyonlarıyla (FX swap tek dönem basit ACT/360, XCCY yıllık par ACT/360) aynen oturur. OIS: PPK "
                            "basamak eğrisi. Tarih, kupon takvimi ve gün sayımı bloğun kendi (yardımcı BK170:CC234): fark yalnız "
                            "eğriden.\n%s.\n%s\n%s%s" % (self.PPK_TIP, self._shift_text(cv.get("off_report"), loc, "Offshore baz"),
                                                        self._shift_text(cv.get("report"), loc), ("\n" + why) if why else "")},
                    {"t": "PPK − piyasa", "k": "s", "b": 1, "f": "hd",
                     "tip": "PPK basamak − Piyasa (mid): forward satırlarında puan, oranlarda bp. Kotalı vadede ~0 (iki eğri de "
                            "kotaya oturur), kotaların arasında iki yöntemin farkı."}]
        for i, r in enumerate(rnums):
            if r == pk.BROKEN_FWD - 1:
                letters = data.get("c") or []
                if "F" in letters and isinstance(rows[i][letters.index("F")], dict):
                    cell = rows[i][letters.index("F")]
                    cell["tip"] = (cell["tip"] + "\n" if cell.get("tip") else "") + (
                        "Eğri ayarınız PPK basamak: piyasa PPK basamak - forward / basit / O/N / XCCY PPK biçimli offshore "
                        "eğrinin düğüm tablosundan (her toplantı basamağında ve kotada düğüm), OIS par Motor'un PPK düğümlerinden "
                        "(çeyrek içinde ln DF doğrusal); yanındaki sütun gerçek Bootstrap (Murex)" if on_ppk else
                        "Bootstrap (Murex) = bugünkü eğriler, Murex'in MTM'i: forward / basit / O/N / XCCY offshore eğriden "
                        "(FX swap ≤9M + XCCY 1Y–10Y, ln DF doğrusal), OIS par BOOT eğrisinden")
                rows[i].extend([dict(c) for c in head])
                continue
            market = calc.get(si, r, f_col) if r in self.BROKEN_DIFF else None
            value = got.get(r)
            if value is None or type(market) is not float:
                rows[i].extend([{"t": "", "k": ""}, {"t": "", "k": ""}])
                continue
            diff = (market - value) if on_ppk else (value - market)          # (PPK − Bootstrap either way)
            rows[i].extend([{"t": numfmt.format_value(value, self._cell_format(book, si, r, f_col), loc), "v": value, "k": "n"},
                            self._diff_cell(diff * self.BROKEN_DIFF[r], self._cell_format(book, si, r, h_col), loc)])
        data["c"] = list(data.get("c") or []) + (["Bootstrap", "PPK fark"] if on_ppk else ["PPK basamak", "PPK fark"])
        data["added"] = int(data.get("added") or 0) + 2

    #: a bond's kind (the desk's list's) from a type letter of a sheet (B / S / T / E: DİBS RV's, the ASW sheet's)
    _KIND_OF_TYPE = {"B": "bill", "S": "fixed", "T": "float", "F": "frn", "E": "cpi"}

    def _bond_rows(self, book, calc, sheet: str, spec: Dict[str, Any], data: Dict[str, Any]) -> None:
        """A list of bonds as its page shows it - display only, every cell stays where it is: the rows that hold no bond
        are left out (the empty rows the desk keeps between its groups and the unused ones below; "+ ISIN ekle" and a
        paste still find them), and with ``order`` the bonds kind by kind (bono, kuponsuz, sabit kuponlu, TLREF, FRN,
        TÜFE - a caption each, as on Tüm Kâğıtlar), by maturity.  ``spec``: the list's ISIN column (``key``), its rows
        (``first``, ``last``); ``order``: the sheet's columns of a bond's type and maturity, when the desk's list does not
        know the bond."""
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows or sheet not in book.model.sheet_index:
            return
        from .rowkeys import isin_of
        si = book.model.sheet_index[sheet]
        key, first, last = col_to_index(spec["key"]), int(spec["first"]), int(spec["last"])
        order = spec.get("order")
        top: List[Tuple[List[Dict[str, Any]], int]] = []
        foot: List[Tuple[List[Dict[str, Any]], int]] = []
        bonds: List[Tuple[str, Any, List[Dict[str, Any]], int]] = []
        for row, r in zip(rows, rnums):
            if not isinstance(r, int) or r < first:
                top.append((row, r))
                continue
            if r > last:
                foot.append((row, r))
                continue
            code = isin_of(calc.get(si, r, key))
            if not code:
                continue
            kind, mat = None, None
            if order:
                b = bd.by_isin(code)
                kind = (b or {}).get("kind") or self._KIND_OF_TYPE.get(calc.get(si, r, col_to_index(order["kind"])))
                mat = date_to_serial(_dt.date.fromisoformat(b["maturity"])) if (b or {}).get("maturity") \
                    else calc.get(si, r, col_to_index(order["maturity"]))
            bonds.append((kind, mat if type(mat) is float else 1e9, row, r))
        out = top
        if not order:
            out += [(row, r) for _, _, row, r in bonds]
        else:
            width = len(rows[0]) if rows else 0

            def caption(text: str) -> List[Dict[str, Any]]:
                # (``grp``: a launchpad box of some of the bonds shows only the captions of their groups)
                return [{"t": text, "k": "s", "b": 1, "cls": "grouphead", "cs": width, "grp": 1}] + [{"sk": 1} for _ in range(width - 1)]

            kinds = [k for k, _, _ in ex.UNI_KINDS]
            for kind, cap, _ in list(ex.UNI_KINDS) + [(None, "Türü bilinmiyor", None)]:
                mine = sorted((x for x in bonds if (x[0] if x[0] in kinds else None) == kind), key=lambda x: (x[1], x[3]))
                if mine:
                    out.append((caption("%s · %d kâğıt" % (cap, len(mine))), 0))
                    out += [(row, r) for _, _, row, r in mine]
        out += foot
        data["rows"] = [row for row, _ in out]
        data["r"] = [r for _, r in out]

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

    #: the two FX swap curves, as the pages name them: DİBS RV's (its BF:BJ) and the ASW page's (EK_FX, its "ASW FX")
    RV_FX_CURVE = "FX swap (offshore ICAP eğrisi)"
    ASW_FX_CURVE = rvfair.FX_CURVE_TEXT                 # (one wording, rvfair's: Genel, the summary and the card use it too)
    #: how the ASW page's curve reads EK_FX's rates (aswfx; the tips of its FX columns)
    FX_RATES_READ = ("FX faizleri kendi kuralıyla okunur - TRYI (9 aya kadar) tek dönem basit ACT/360, TRYSAQ (1 yıldan) yıllık ACT/360 par, "
                     "masanın dosyasındaki gibi; 18A kota değil, hesaplanır: offshore eğrinin XCCY 1Y–2Y arasında 18A iskonto faktörü, "
                     "Ayarlar'daki eğri interpolasyonunuzla (Bootstrap / PPK basamak) - ve sayfaya, vadesinde aynı iskonto faktörünü "
                     "veren kendi kuralındaki par faiz olarak girer")

    @classmethod
    def _rv_fx_tips(cls) -> Dict[str, str]:
        """DİBS RV's FX swap columns (BF:BJ), each with the curve it is of named - the ASW page's FX swap ASW is another."""
        curve = ("%s: Forward'daki offshore TRY iskonto eğrisi (9A'ya kadar FX swap ima, sonra XCCY; OFF_GUN / OFF_LNDF). DİBS ASW "
                 "sayfasının ASW FX'i başka bir eğri: %s" % (cls.RV_FX_CURVE, cls.ASW_FX_CURVE))
        return {"BF": "ASW, %s" % curve, "BG": "Uydurulmuş ASW (a + b·t + c·t², sabit kuponlular), %s" % curve,
                "BH": "ASW FX − uydurulmuş (bp; + ucuz), %s" % curve, "BI": "Pahalı / ucuz eşiği aşınca, %s" % curve,
                "BJ": "ASW FX − ASW OIS (bp), %s" % curve}

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
        fx_tips = self._rv_fx_tips()
        for i, r in enumerate(rnums):
            if r == 4:
                for col, tip in fx_tips.items():                 # (the FX swap columns: which curve they are of)
                    j = data["c"].index(col) if col in (data.get("c") or []) else None
                    if j is not None and j < len(rows[i]) and isinstance(rows[i][j], dict) and not rows[i][j].get("sk"):
                        rows[i][j] = dict(rows[i][j], tip=tip)
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
    #: stands behind that price (the yield's O/N equivalent too, 26.11.2026)
    _RV_PRICED = ("BIST basit getiri", "BIST bileşik getiri", "Getiri − OIS", "ASW (S/B)", "Pahalı/ucuz", "Sinyal", "ASW FX",
                  "ON karşılık")

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
                        "Getiri − OIS", "ASW (S/B)", "Uydurulmuş ASW (bp)", "Pahalı/ucuz (bp", "Sinyal",
                        "Mod. süre", "DV01 TL", "C+R (bp)", "Son işlem tarihi", "Son işlem fiyatı", "Bugün düşük", "Bugün yüksek",
                        "ON karşılık")
                # (DİBS RV's own FX columns are on the offshore ICAP curve: the card's FX swap figures are DİBS ASW's, below)
                rv_fx = ("ASW FX", "Uydurulmuş ASW FX", "Pahalı/ucuz FX", "Sinyal FX")
                q = self._rv_quote(calc, si, info["row"])
                for c in range(1, sh.max_col + 1):
                    cap = sh.consts.get(4 * COLS + c)
                    if isinstance(cap, str) and any(cap.strip().startswith(w) for w in want) and not cap.strip().startswith(rv_fx):
                        cell = R.cell(calc, si, info["row"], c, loc)
                        if str(cell.get("t") or "").strip():
                            item = {"name": cap.strip(), "t": cell.get("t"), "c": cell.get("c")}
                            if q["stale"] and cap.strip().startswith(self._RV_PRICED):      # worked out of no live quote
                                item.update(soft=True, tip=q["tip"])
                            out["rv"].append(item)
                # (the yield's O/N equivalent - a column of its own right of the table - beside the yield, as the page shows it)
                on = next((x for x in out["rv"] if x["name"].startswith("ON karşılık")), None)
                if on is not None:
                    out["rv"].remove(on)
                    at = next((k + 1 for k, x in enumerate(out["rv"]) if x["name"].startswith("BIST bileşik getiri")), len(out["rv"]))
                    out["rv"].insert(at, on)
                # the fair yield and price on each fitted ASW curve and the bond's FX swap figures (DİBS ASW, on the FX swap
                # implied curve) - as the trading summary has them - after the OIS curve's own figures
                from . import rvfair
                fx = self._fx_curve(user_key(user) if user else None)
                fits = rvfair.read_fits(calc, si, fx)
                f = rvfair.fair(calc, si, info["row"], fits, fx)
                valor, own = calc.get(si, info["row"], parse_a1("P1") % COLS), calc.get(si, info["row"], parse_a1("T1") % COLS)

                def item(name: str, c: Dict[str, Any]) -> Dict[str, Any]:
                    return {"name": name, "t": c["t"], "tip": c.get("tip"), "soft": "soft" in (c.get("cls") or "")}

                fair = [item("%s (OIS eğrisi)" % what, c) for what, c in zip(("Adil getiri", "Adil fiyat"),
                                                                              self._fair_cells(f["ois"], "ois", fits, valor, own, loc))]
                fx_own, _, fx_rich, fx_signal = self._fx_cells(f["fx"], calc.get(si, 2, parse_a1("P1") % COLS), loc)
                for name, c in (("ASW FX ima (bp)", fx_own), ("Pahalı/ucuz FX ima (bp, + ucuz)", fx_rich), ("Sinyal FX ima", fx_signal)):
                    if str(c.get("t") or "").strip():
                        fair.append(item(name, self._soft(c, q["tip"]) if q["stale"] and c["t"] != "–" else c))
                fair += [item("%s (FX swap ima eğrisi)" % what, c) for what, c in zip(("Adil getiri", "Adil fiyat"),
                                                                                   self._fair_cells(f["fx"], "fx", fits, valor, own, loc))]
                at = max([k + 1 for k, x in enumerate(out["rv"]) if x["name"].startswith("Sinyal")] or [len(out["rv"])])
                out["rv"][at:at] = fair
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

    # ================================================================== where today's Bloomberg hits went
    #: the status window's names of what a hit was for (``marketdata/bloomberg.py`` KINDS)
    USAGE_KINDS = {"first": "İlk cevap (sayfanın hiç almadığı)", "poll": "Akmayan kota sorgusu",
                   "static": "Sabit alanlar (günde bir)", "daily": "Günlük alanlar (günde bir; tanınmayanlar da)",
                   "hourly": "Gün içinde değişen, akmayan (saatte bir)", "history": "Tarihçe / BDH",
                   "user": "Hesapla / kullanıcı isteği", "resync": "Kuyruk taşması onarımı", "bars": "Gün içi barlar (quant)",
                   "probe": "Bloomberg limiti denemesi"}
    #: ... and of what is asked outside the workbooks' cells
    USAGE_OUTSIDE = {"HIST": "Tarihçe (gün sonu, quant, FX)", "REF": "Kâğıt Fiyat Yükleme (Hesapla)",
                     "BAR": "Gün içi barlar (quant)"}

    def market_usage(self, top: int = 10) -> Dict[str, Any]:
        """Where today's Bloomberg hits went - by kind, the ``top`` sheets and fields - with the day's budget, Bloomberg's
        own limit, the desk's hours and what is polled or kept current by the stream (the status window; on demand: the
        sheets come from which cell asks for which key, ``_market_callers``)."""
        prov = self.provider
        try:
            st = prov.status() or {}
        except Exception:  # noqa: BLE001
            st = {}
        usage_of = getattr(prov, "usage", None)
        try:
            usage = usage_of() if usage_of is not None and self.mode == "live" else {}
        except Exception:  # noqa: BLE001
            usage = {}
        callers = self._market_callers() if usage else {}
        places = self._cell_places() if usage else {}
        sheets: Dict[Tuple[str, str, Optional[str]], int] = {}
        fields: Dict[str, int] = {}
        for key, n in usage.items():
            kind = key[0]
            if kind in self.USAGE_OUTSIDE:
                where = (self.USAGE_OUTSIDE[kind], "", None)
                field = "gün içi bar" if kind == "BAR" else ("BDH " if kind == "HIST" else "") + str(key[2])
            else:
                field = ("%s %s" % (kind, key[2])) if kind in ("BDH", "BDS") else str(key[2])
                cells = sorted(callers.get(key, ()))
                if cells:
                    bid, si, rc = cells[0]
                    book = self.books[bid]
                    sheet = book.model.sheets[si].name
                    r, c = divmod(rc, COLS)
                    page = next((pg for r1, c1, r2, c2, pg, _pn in places.get((bid, sheet), ())
                                 if r1 <= r <= r2 and c1 <= c <= c2), None)
                    where = (book.title, sheet, page)
                else:
                    # (the FX pages' quotes, a bond's facts, a key of another day's cells no page reads any more)
                    where = ("Diğer", "FX sayfaları, kâğıt bilgileri, eski günün anahtarları", None)
            sheets[where] = sheets.get(where, 0) + int(n)
            fields[field] = fields.get(field, 0) + int(n)
        hits = int(st.get("hits_today") or 0)
        budget = int(st.get("budget") or 0)
        kinds = st.get("kinds") or {}
        return {"mode": self.mode, "hits": hits, "budget": budget, "max_hits": int(st.get("max_hits") or 0),
                "used": round(100.0 * hits / budget, 1) if budget else None, "tier": int(st.get("tier") or 0),
                "kinds": [{"kind": k, "label": self.USAGE_KINDS.get(k, k), "hits": int(n)}
                          for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]) if n],
                "sheets": [{"book_title": b, "sheet": s, "page": pg, "hits": n}
                           for (b, s, pg), n in sorted(sheets.items(), key=lambda kv: -kv[1])[:top]],
                "fields": [{"field": f, "hits": n} for f, n in sorted(fields.items(), key=lambda kv: -kv[1])[:top]],
                "bbg_limit": st.get("bbg_limit") or "", "bbg_limit_text": st.get("bbg_limit_text") or "",
                "desk": st.get("desk"), "quiet": bool(st.get("quiet")), "polled": st.get("polled") or {},
                "poll_every": st.get("poll_every"), "poll_empty": st.get("poll_empty"), "fed": int(st.get("fed") or 0),
                "gen": self.gen}

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

    # ================================================================== the curve between quoted tenors (interp.py)
    def interp_settings(self, user: Optional[str]) -> Dict[str, Any]:
        """Ayarlar → Eğri interpolasyonu: the user's choice (Bootstrap (Murex) / PPK basamak), what each is, whether the PPK
        curve could be made."""
        key = self.require_user(user)
        return self.et.call(self.interp.settings, key)

    def set_interp(self, user: Optional[str], mode: Any) -> Dict[str, Any]:
        """The user's choice set: PPK basamak their own input, Bootstrap (the default) none - their pages back to
        everybody's when they have no other input of their own."""
        key = self.require_user(user)
        if not self.interp.available:
            raise ServiceError("bu çalışma kitabında eğri ayarı yok (%s eklenemedi)" % ex.INTERP_SHEET)
        text = " ".join(str(mode or "").split()).lower()
        if text in ("ppk", "ppk basamak", ex.INTERP_PPK.lower()):
            res = self.set_inputs(key, "tto", [{"ref": self.interp.mode_ref, "value": ex.INTERP_PPK}])
            if res.get("errors"):
                raise ServiceError("; ".join(res["errors"]))
        elif text in ("boot", "bootstrap", "murex", ex.INTERP_BOOT.lower()):
            self.reset_inputs(key, "tto", [self.interp.mode_ref])
        else:
            raise ServiceError("eğri şunlardan biri olmalı: %s" % ", ".join(ex.INTERP_CHOICES))
        return self.interp_settings(key)

    # ================================================================== the desk's list of curve points (curvepoints.py)
    def curve_points(self, user: Optional[str]) -> Dict[str, Any]:
        """Ayarlar → Eğri noktaları: the desk's list of the points each TRY curve is built from - everyone sees it (a
        computed point on their own interpolation setting); ``can_edit`` for an administrator."""
        key = self.require_user(user)
        if not self.interp.available:
            return {"available": False}
        return self.curvepoints.payload(key, admin=self._is_admin(key))

    def set_curve_points(self, user: Optional[str], data: Any) -> Dict[str, Any]:
        """An administrator's change of the list (it moves everyone's curves; logged) - curvepoints.CurvePoints.change.
        A ticker point waits for ``confirm`` of its stated cost: the answer then says so (``needs_confirm``, ``cost``) and
        nothing is saved or asked of Bloomberg."""
        key = self.require_admin(user)
        if not self.interp.available:
            raise ServiceError("bu çalışma kitabında eğri ayarı yok (%s eklenemedi)" % ex.INTERP_SHEET)
        res = self.curvepoints.change(key, data if isinstance(data, dict) else {})
        out = self.curvepoints.payload(key, admin=True)
        out.update(res)
        return out

    # ================================================================== Fiyatlama (pricing.py)
    #: what a user typed on the pricing page: kept with their account, per asset
    PRICING_KEY = "pricing."

    def pricing(self, user: Optional[str], payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fiyatlama: the user's instrument - TRY OIS, FRA, XCCY, FX forward at any start and maturity - on the TRY curves
        both ways, their own curve setting first: the mid, the DV01 bucket by bucket and, with a price, the NPV - a price
        typed as an NPV or an upfront gives the rate (outright) that prices to it -, and the Toplu box's lines (``bulk``)
        off the same curves (:mod:`tto.pricing`).  ``payload``: what they typed (kept with their account, per asset); none:
        what they typed last.  Inputs it cannot price come back with ``error`` - the page says it beside them, the inputs
        kept."""
        key = self.require_user(user)
        inputs = pr.clean_inputs(payload, self.store.get(self.PRICING_KEY + key))
        if payload is not None:
            self.store.put(self.PRICING_KEY + key, inputs)
        out = self.et.call(self._pricing, key, inputs)
        out.update(inputs=inputs, gen=self.gen)
        return out

    def _pricing(self, user: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        book = self.books.get("tto")
        cv = None
        if book is not None:
            calc = self._calc(user, book)
            cv = self._try_curves(book, calc)
        if not cv:
            return {"available": False, "error": "bu çalışma kitabında TRY eğrileri yok"}
        method = self.interp.mode(user)
        out: Dict[str, Any] = {"available": True, "curve": method, "curve_text": pr.METHOD_TEXT[method]}
        base = self.interp.boot_of(book, calc)               # (the true bootstrap whatever the setting: its quotes, nodes)
        idx = book.model.sheet_index
        try:
            mk = pr.read(lambda sheet, r, c: base.get(idx[sheet], r, c))
        except pr.PricingError as exc:
            out["error"] = str(exc)
            return out
        curves = pr.Curves(cv, mk, self.__dict__.setdefault("_pricing_kept", {}))
        try:
            out.update(pr.price(inputs, curves, method))
        except pr.PricingError as exc:
            out["error"] = str(exc)
        # the Toplu box: its lines off the same curves (each its own error; the page's instrument's error not theirs)
        out["bulk"] = pr.bulk(inputs, curves, method)
        asset = inputs["asset"]
        if "error" not in out and out.get("label"):
            out["hedges"] = pr.hedges(out, curves)              # C3: each bucket's opposite TRY OIS (OIS / FRA only)
            if asset == pr.FX:
                # the forward card (28.11.2026): every source at the value date, the ladder, the quote
                try:
                    out["card"] = self._forward_card(user, book, calc, inputs, curves, out["methods"][0], out["size"]["size"])
                except (pr.PricingError, ValueError, ZeroDivisionError, KeyError, TypeError) as exc:
                    log.warning("forward kartı: %s", exc, exc_info=True)
                    out["card"] = {"error": "forward kartı hesaplanamadı: %s" % exc}
        if asset != pr.FX:
            self._drop_fwd_layers(user, book)
        return out

    # ------------------------------------------------------------------ Fiyatlama: the forward card (28.11.2026)
    #: FORWARD KOTASYON's matrices (EK_FWD, extras._tto_forward / _tto_fwd_eur): the general row, the rows a date can
    #: be evaluated in (their valör B is an input), the curve's cell - and the columns read: A label, B valör, C days,
    #: D / E spread, H / I puan, J / K fwd, L OIS %, M / N TRY %, O USD / EUR %, R / S RET %, V / W market spread (bp)
    FWD_MATRIX = {"USDTRY": (ex.FWD_ALL, ex.FWD_ROWS, 2), "EURTRY": (ex.FWD_EUR_ALL, ex.FWD_EUR_ROWS, ex.FWD_EUR_ALL - 2)}
    FWD_COLS = {"label": 1, "valor": 2, "days": 3, "sp_bid": 4, "sp_ask": 5, "pts_bid": 8, "pts_ask": 9, "fwd_bid": 10,
                "fwd_ask": 11, "ois": 12, "try_bid": 13, "try_ask": 14, "ccy": 15, "ret_bid": 18, "ret_ask": 19,
                "mkt_bid": 22, "mkt_ask": 23}
    #: the columns a date's evaluation reads that depend on the valör only (a user's "Elle değer" on one of them, or on a
    #: helper X..AL, makes the row unusable for another date)
    FWD_PURE = (3, 12, 15, 18, 19, 22, 23) + tuple(range(24, 39))
    #: a row's columns looked at for anything typed (A … CB: the matrix, its helpers and stores to AY, room for more)
    FWD_ROW_LAST = 80
    #: the VİOP sheet's contracts: columns M … X; rows 1 (the ticker, one column to the left), 9 expiry, 10 VKGS, 13 / 25
    #: implied TRY bid / ask (decimal), 14 / 26 points, 16 / 28 price bid / ask
    VIOP_CONTRACTS = (13, 24)
    VIOP_ROW = {"expiry": 9, "days": 10, "try_bid": 13, "pts_bid": 14, "px_bid": 16, "try_ask": 25, "pts_ask": 26, "px_ask": 28}
    #: the layers a user's forward card is evaluated in at most (10 dates each)
    FWD_LAYERS = 3

    def _fwd_layer_keys(self, user: str) -> List[Tuple[str, str, int]]:
        # (the user first, as every layer of a user is keyed: the idle sweep and copies.drop give them back with the user)
        return [(user, "pricing-fwd", k) for k in range(self.FWD_LAYERS)]

    def _drop_fwd_layers(self, user: str, book, keep: int = 0) -> None:
        for key in self._fwd_layer_keys(user)[keep:]:
            book.engine.drop_layer(key)

    def _forward_card(self, user: str, book, calc, inputs: Dict[str, Any], curves: "pr.Curves", method: str,
                      size: Optional[float]) -> Dict[str, Any]:
        """The forward card of the user's FX forward (:func:`tto.pricing.forward_card`): FORWARD KOTASYON's own row at
        every date it shows - the value date, the ladder's tenors and PPK meetings - read from the user's matrix where
        one of its rows is at that date (as they see it), else evaluated in a layer of the engine over the user's
        calculation with a row's valör set to the date (``engine.layer``: nothing of the user's changes, nothing is
        kept); RET, the market's spread, the USD / EUR rate from the same row; VİOP's contracts; Fiyatlama's offshore
        curve (the user's ``method``) for the offshore mid.  Calculation thread."""
        mk = curves.mk
        f = inputs["by"][pr.FX]
        deal = pr.instrument(pr.FX, f, mk)
        pair = deal.pair
        idx = book.model.sheet_index
        si = idx[ex.FWD_SHEET]
        gen_row, (r1, r2), curve_row = self.FWD_MATRIX[pair]
        c = self.FWD_COLS
        num = lambda v: v if type(v) is float and v == v else None          # noqa: E731
        gen = pr.FwdGeneral(curve=str(calc.get(si, curve_row, 2) or ""), mode=str(calc.get(si, gen_row, 2) or ""),
                            spread_bid=num(calc.get(si, gen_row, 4)), spread_ask=num(calc.get(si, gen_row, 5)),
                            spot_bid=num(calc.get(si, gen_row, 6)), spot_ask=num(calc.get(si, gen_row, 7)))
        # the meetings (Motor's list from MPC1: name, decision day, the implied step OIS_MAIN!R shows)
        mo, oi = idx["Motor"], idx["OIS_MAIN"]
        meetings = []
        for k in range(80):
            day, eff = num(calc.get(mo, 5 + k, 2)), num(calc.get(mo, 5 + k, 3))
            if day is None or eff is None or eff >= 99999:
                break
            meetings.append({"name": calc.get(mo, 5 + k, 1), "date": day, "step": num(calc.get(oi, 10 + k, 18))})
        ladder = pr.ladder_dates(deal.start, deal.end, mk.holidays[pair], meetings)
        dates = sorted({deal.end} | {r["date"] for r in ladder})
        # the user's own matrix rows by their valör (read as they see them)
        own_rows: Dict[float, int] = {}
        for r in range(r1, r2 + 1):
            v = num(calc.get(si, r, c["valor"]))
            if v is not None and v not in own_rows:
                own_rows[v] = r
        ov = self._overlay(user, book) if user else {}
        desk = book.engine.input_value[si]                                  # (a value the desk typed for everyone)
        typed = lambda r, cols: any((si, r * COLS + col) in ov or r * COLS + col in desk for col in cols)      # noqa: E731
        # the rows a date is evaluated in: first the ones with nothing of the user's typed in them (but their valör) - the
        # row is then the matrix itself at the date, its TRY % / fwd / puan read as it computes them, whatever its rule;
        # then the ones typed into only where the date's own numbers do not look (their spread etc.: the rule applied here)
        clean = [r for r in range(r1, r2 + 1) if not typed(r, [col for col in range(1, self.FWD_ROW_LAST + 1) if col != c["valor"]])]
        free = clean + [r for r in range(r1, r2 + 1) if r not in clean and not typed(r, self.FWD_PURE)]

        def point(src, r: int, day: float, own: bool, label: Optional[str] = None) -> pr.FwdPoint:
            g = lambda key: num(src.get(si, r, c[key]))                    # noqa: E731
            mine = None
            if own:
                mine = {k: g(k) for k in ("try_bid", "try_ask", "fwd_bid", "fwd_ask", "pts_bid", "pts_ask", "sp_bid", "sp_ask")}
                mine["label"] = label if label is not None else str(src.get(si, r, c["label"]) or "")
            return pr.FwdPoint(date=day, days=g("days"), ois=g("ois"), ccy=g("ccy"), ret_bid=g("ret_bid"), ret_ask=g("ret_ask"),
                               mkt_bid=g("mkt_bid"), mkt_ask=g("mkt_ask"), own=mine)

        points: Dict[float, pr.FwdPoint] = {}
        todo = []
        for day in dates:
            if day in own_rows:
                points[day] = point(calc, own_rows[day], day, True)
            else:
                todo.append(day)
        if todo and not free:
            raise pr.PricingError("FORWARD KOTASYON'un satırlarında elle değer var: tarih hesaplanamadı")
        batches = [todo[k:k + len(free)] for k in range(0, len(todo), len(free))] if todo else []
        if len(batches) > self.FWD_LAYERS:
            batches = batches[:self.FWD_LAYERS]                 # (the farthest ladder rows left out: never the valör)
            if deal.end in todo and not any(deal.end in b for b in batches):
                batches[-1][-1] = deal.end
        parent = calc
        for k, days in enumerate(batches):
            layer = book.engine.layer(self._fwd_layer_keys(user)[k], parent,
                                      {(si, r * COLS + c["valor"]): float(day) for r, day in zip(free, days)})
            for r, day in zip(free, days):
                points[day] = point(layer, r, day, r in clean, label="")    # (a clean row: the matrix's own numbers)
        self._drop_fwd_layers(user, book, keep=len(batches))
        # VİOP's USDTRY contracts (none for EURTRY)
        contracts = []
        if pair == "USDTRY" and "VIOP" in idx:
            vi = idx["VIOP"]
            for col in range(self.VIOP_CONTRACTS[0], self.VIOP_CONTRACTS[1] + 1):
                got = {k: num(calc.get(vi, r, col)) for k, r in self.VIOP_ROW.items()}
                ticker = calc.get(vi, 1, col - 1)
                got["name"] = str(ticker).replace(" Curncy", "").strip() if isinstance(ticker, str) else ""
                if got["expiry"] is not None and got["try_bid"] is not None and got["try_ask"] is not None:
                    contracts.append(got)
        off = curves.curve(pr.OFF, method)
        off_mids = {day: ((pr.forward(deal, off), (off.df(deal.start - deal.spot) / off.df(deal.end - deal.spot) - 1.0)
                           * 360.0 / (deal.end - deal.start)) if off is not None and day == deal.end
                          else pr.off_mid(deal, day, off, mk))
                    for day in points}
        card = pr.forward_card(deal, gen, points, contracts, off_mids, ladder, f.get("source") or pr.DEFAULT_SOURCE,
                               f["side"], size)
        card["label"] = deal.label
        card["client"] = f.get("client") or ""
        card["sources_text"] = pr.SOURCE_TEXT
        return card

    def pricing_quote(self, user: Optional[str], body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fiyatlama's forward card, "Kotasyon kopyala" / "Done" / "Done değil": the picked source's quote of the user's FX
        forward priced now, as text to send (``language`` tr / en), logged in the quote log (tto/quotelog.py) with the
        client typed - ``status`` "open" (a copy; default), or "done" / "not_done" when the trader says so without having
        copied it.  ``source``: another source than the one kept (the card's own choice is kept with the inputs)."""
        key = self.require_user(user)
        b = body if isinstance(body, dict) else {}
        status = str(b.get("status") or "open")
        if status not in ql.STATUSES:
            raise ServiceError("durum open, done ya da not_done olmalı")
        fields = {k: b[k] for k in ("source", "client") if b.get(k) is not None}
        # (the card's client / source kept with the FX forward's inputs; the page's instrument as it is)
        stored = pr.clean_inputs({"by": {pr.FX: fields}} if fields else None, self.store.get(self.PRICING_KEY + key))
        if fields:
            self.store.put(self.PRICING_KEY + key, stored)
        inputs = dict(stored, asset=pr.FX)
        got = self.et.call(self._pricing, key, inputs)
        card = got.get("card")
        if got.get("error") or not card or card.get("error"):
            raise ServiceError(got.get("error") or (card or {}).get("error") or "forward kartı yok")
        lang = "en" if str(b.get("language") or "").lower() == "en" else "tr"
        f = inputs["by"][pr.FX]
        label = pr.when_label(pr.parse_when(f["end"]) or ("d", card["valor"]))
        today = date_to_serial(_dt.date.today())
        text = pr.card_quote_text(card, label, lang, today)
        q = next(s for s in card["sources"] if s["id"] == card["picked"])
        deal = card["deal"]
        rec = {"product": "FX forward", "instrument": "%s forward %s" % (card["pair"], label), "pair": card["pair"],
               "side": deal["side"], "source": "Fiyatlama · forward kartı · %s" % pr.SOURCE_TEXT[card["picked"]],
               "page": "fiyatlama", "client": f.get("client") or "", "size": deal.get("amount"), "value_date": card["valor"],
               "levels": {"bid": q["fwd"].get("bid"), "ask": q["fwd"].get("ask"), "unit": "kur", "kind": "outright",
                          "text": pr._fmt(q["fwd"].get("bid"), 4, "tr") + " / " + pr._fmt(q["fwd"].get("ask"), 4, "tr")},
               "text": text}
        rec, _ = ql.clean_new(rec)
        rec["spot"] = deal.get("spot")
        rec["level"] = deal.get("level")
        qid = self.store.add_quote_log(self.today_iso(), rec, status, key)
        return {"text": text, "language": lang, "id": qid, "quote": self.store.quote_log_item(qid), "card": card}

    # ------------------------------------------------------------------ Fiyatlama: Pozisyona ekle (deneme) - C3
    def pricing_trial(self, user: Optional[str]) -> Dict[str, Any]:
        """"Pozisyona ekle (deneme)": DV01 Risk's buckets + the user's Fiyatlama instrument, before and after - the total
        DV01, the four VaRs and the PPK decision risk - by DV01 Risk's own formulas in a layer of the engine over the
        user's calculation (tto/pricing.py ``TRIAL_TEXT``); nothing is saved."""
        key = self.require_user(user)
        inputs = pr.clean_inputs(None, self.store.get(self.PRICING_KEY + key))
        return self.et.call(self._pricing_trial, key, inputs)

    def _pricing_trial(self, user: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
        got = self._pricing(user, inputs)
        if got.get("error") or not got.get("label"):
            return {"available": False, "error": got.get("error") or "fiyatlanan işlem yok"}
        book = self.books.get("tto")
        idx = book.model.sheet_index
        if pr.DV01_SHEET not in idx:
            return {"available": False, "error": "DV01 Risk sayfası yok"}
        si = idx[pr.DV01_SHEET]
        calc = self._calc(user, book)
        num = lambda v: v if type(v) is float and v == v else None          # noqa: E731
        col = pr.DV01_COL
        n = pr.DV01_LAST - pr.DV01_FIRST + 1
        sign = num(calc.get(si, *pr.DV01_SIGN)) or 1.0
        buckets = [(str(calc.get(si, pr.DV01_FIRST + k, col["name"]) or ""), num(calc.get(si, pr.DV01_FIRST + k, col["days"])))
                   for k in range(n)]
        method = got["methods"][0]
        usdtry = got["usdtry"]
        pillars = [(b["name"], b["day"] if b["day"] is not None else 0.0, (b["dv01"].get(method) or 0.0) * usdtry)
                   for b in got["buckets"]["rows"] if b.get("pillar")]
        deal = pr.to_buckets(pillars, buckets)                # TL/bp, + = gains when rates rise
        family = got["family"]
        ov = self._overlay(user, book)
        eng = book.engine
        add: Dict[Tuple[int, int], Any] = {}
        cols = [col["tlref"], col["dv01"]] if family == pr.ON else [col["offshore"]]
        for k, d in enumerate(deal):
            if not d:
                continue
            for cc in cols:
                r = (pr.DV01_FIRST if cc == col["dv01"] else pr.VAR_FIRST) + k
                rc = r * COLS + cc
                if cc == col["dv01"] and rc in eng.fml[si] and (si, rc) not in ov and rc not in eng.input_value[si]:
                    continue                                   # (a formula default - Onshore + TLREF: it follows the column)
                add[(si, rc)] = (num(calc.get(si, r, cc)) or 0.0) + d / sign
        key = (user, "pricing-trial")
        after = eng.layer(key, calc, add)
        try:
            def read(src) -> Dict[str, Any]:
                out = {"buckets": [(num(src.get(si, pr.DV01_FIRST + k, col["dv01"])) or 0.0) * sign for k in range(n)],
                       "total": num(src.get(si, *pr.DV01_TOTAL)),
                       "var": [{"name": str(src.get(si, r, 23) or ""), "dv01": num(src.get(si, r, 24)), "var": num(src.get(si, r, 25))}
                               for r in range(pr.VAR_ROWS[0], pr.VAR_ROWS[1] + 1)],
                       "var_status": str(src.get(si, *pr.VAR_STATUS) or ""), "ppk": []}
                for r in range(pr.PPK_ROWS[0], pr.PPK_ROWS[1] + 1):
                    name = src.get(si, r, 2)
                    if not isinstance(name, str) or not name.strip():
                        continue
                    out["ppk"].append({"name": name, "date": num(src.get(si, r, 3)), "period": num(src.get(si, r, 6)),
                                       "decision": num(src.get(si, r, 7)), "pnl25": num(src.get(si, r, 10))})
                return out
            before, then = read(calc), read(after)
        finally:
            eng.drop_layer(key)
        rows = [{"name": buckets[k][0], "before": before["buckets"][k], "deal": deal[k], "after": then["buckets"][k]}
                for k in range(n)]
        var = [dict(b, dv01_after=a["dv01"], var_after=a["var"]) for b, a in zip(before["var"], then["var"])]
        ppk = [dict(b, decision_after=a["decision"], pnl25_after=a["pnl25"], period_after=a["period"])
               for b, a in zip(before["ppk"], then["ppk"])]
        return {"available": True, "label": got["label"], "side": got["side"], "family": family, "method": method,
                "usdtry": usdtry, "sign": sign, "buckets": rows, "total": {"before": before["total"], "after": then["total"]},
                "deal_total": sum(deal), "var": var, "var_status": then["var_status"], "ppk": ppk, "text": pr.TRIAL_TEXT,
                "columns": "TLREF + Pozisyon" if family == pr.ON else "Offshore", "saved": False}

    # ================================================================== Kotasyon defteri (quotelog.py)
    def quote_log_add(self, user: Optional[str], payload: Any) -> Dict[str, Any]:
        """``POST /api/quote-log``: a quote given (tto/quotelog.py) - ``{id, quote}``."""
        key = self.require_user(user)
        try:
            rec, status = ql.clean_new(payload)
        except ql.QuoteLogError as exc:
            raise ServiceError(str(exc))
        qid = self.store.add_quote_log(self.today_iso(), rec, status, key)
        return {"id": qid, "quote": self.store.quote_log_item(qid)}

    def quote_log_set(self, user: Optional[str], qid: Any, payload: Any) -> Dict[str, Any]:
        """``POST /api/quote-log/{id}``: a quote done / not done / open again, the trade it became, its client."""
        key = self.require_user(user)
        try:
            status, fields = ql.clean_update(payload)
        except ql.QuoteLogError as exc:
            raise ServiceError(str(exc))
        got = self.store.set_quote_log(int(qid), status, fields, key)
        if got is None:
            raise ServiceError("kota bulunamadı: %s" % qid, 404)
        return {"quote": got}

    def quote_log(self, user: Optional[str], query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """``GET /api/quote-log?from=&to=``: the quotes of the days (today without them) and the hit ratio by client and
        by product (tto/quotelog.py)."""
        self.require_user(user)
        q = query or {}
        today = self.today_iso()
        try:
            first, last = ql.period(q.get("from"), q.get("to"), today)
        except ql.QuoteLogError as exc:
            raise ServiceError(str(exc))
        quotes = self.store.quote_log(first, last)
        return {"from": first, "to": last, "today": today, "quotes": quotes, "hit": ql.hit(quotes),
                "statuses": dict(ql.STATUS_TEXT)}

    # ================================================================== Swaption (swaption.py)
    #: forward histories kept, by expiry × tenor and what they are made of (a page refresh builds none again)
    SWAPTION_KEPT = 32

    def swaption(self, user: Optional[str], query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Swaption: a TRY OIS swaption, to look at only - the underlying (Fiyatlama's forward-start TRY OIS) on the
        viewer's curve with the other beside it, the realized vols of its forward from the history's closes, payer,
        receiver and straddle with their greeks at the vol used - realized over 60 changes, or one typed in bp/day,
        bp/year or % Black (:mod:`tto.swaption`).  ``query``: the page's inputs (nothing is stored); inputs it cannot
        read - an expiry + tenor beyond 10Y among them - are a 400 with the reason in Turkish."""
        key = self.require_user(user)
        try:
            inputs = sw.read_inputs(query or {})
        except sw.SwaptionError as exc:
            raise ServiceError(str(exc))
        got = self.et.call(self._swaption_market, key)
        if "error" in got:
            return {"available": False, "error": got["error"]}
        hist = self._swaption_history(inputs["expiry_m"], inputs["tenor_m"], got["mk"])
        try:
            out = sw.price(inputs, got["cv"], got["mk"], got["method"], got["today"], hist)
        except (sw.SwaptionError, pr.PricingError) as exc:
            raise ServiceError(str(exc))
        out.update(available=True, history=hist["info"], gen=self.gen)
        return out

    def _swaption_market(self, user: str) -> Dict[str, Any]:
        """The user's TRY curves both ways (:meth:`_try_curves`), what pricing reads beside them (their Bootstrap
        calculation: :func:`tto.pricing.read`), their curve setting and the market day (the workbook's TODAY())."""
        book = self.books.get("tto")
        if book is None:
            return {"error": "bu çalışma kitabında TRY eğrileri yok"}
        calc = self._calc(user, book)
        cv = self._try_curves(book, calc)
        if not cv:
            return {"error": "bu çalışma kitabında TRY eğrileri yok"}
        base = self.interp.boot_of(book, calc)               # (the true bootstrap whatever the setting: its quotes, nodes)
        idx = book.model.sheet_index
        try:
            mk = pr.read(lambda sheet, r, c: base.get(idx[sheet], r, c))
        except pr.PricingError as exc:
            return {"error": str(exc)}
        return {"cv": cv, "mk": mk, "method": self.interp.mode(user), "today": book.engine.clock.today()}

    def _swaption_closes(self, mk: pr.Market) -> Tuple[Tuple, Dict[float, Dict[str, float]], FrozenSet[float], Dict[str, Any]]:
        """The TRY OIS closes the history keeps (``_vol_curves``: months -> {ISO day: %}), the TRY holidays the past
        days are dated with - the workbook's list and the week days without a TLREF fixing (the history's own rule,
        ``History._holidays``: the list holds the holidays ahead only) - and what the closes cover; first what they were
        read for.  Read once per revision of the history and of the TRY holiday list (``mk``'s)."""
        mark = (self.history.rev, hash(mk.holidays["TRY"]))
        hit = getattr(self, "_swaption_read", None)
        if hit is not None and hit[0] == mark:
            return hit
        curves, months, info = self._vol_curves()
        closes = {float(months["OIS"][t]): s for t, s in curves["OIS"].items() if s and (months["OIS"].get(t) or 0) >= 1}
        snap = self.history.snapshot()
        ref = next((d for d in snap["defs"] if d.group == "ref"), None)
        tlref: Dict[str, float] = {}
        if ref is not None:
            start = (snap["today"] - _dt.timedelta(days=600)).isoformat()
            tlref = ref.pick(self.store.hist_many(ref.ids(), start))[1]
        serials, _ = self.history._holidays(snap, tlref)
        out = (mark, closes, frozenset(float(x) for x in serials), {"first": info["first"], "last": info["last"],
                                                                   "days": info["days"], "source": info["source"]})
        self._swaption_read = out
        return out

    def _swaption_history(self, expiry_m: int, tenor_m: int, mk: pr.Market) -> Dict[str, Any]:
        """The forward's history for an expiry × tenor (:func:`tto.swaption.forward_history`), kept until the history,
        Motor's grid or the holidays change; each day's curve kept apart, for every expiry × tenor.  Made on the
        request's thread, not the calculation thread (pure arithmetic on the closes): one request at a time."""
        with self.__dict__.setdefault("_swaption_lock", threading.Lock()):
            mark, closes, hol, info = self._swaption_closes(mk)
            key = (expiry_m, tenor_m, mark, tuple(mk.nodes), tuple(m for m, _ in mk.ois_quotes), hash(hol))
            kept = self.__dict__.setdefault("_swaption_kept", {})
            hit = kept.get(key)
            if hit is None:
                hit = sw.forward_history(closes, expiry_m, tenor_m, mk, hol, self.__dict__.setdefault("_swaption_days", {}))
                kept[key] = hit
                while len(kept) > self.SWAPTION_KEPT:
                    kept.pop(next(iter(kept)))
        return dict(hit, info=info)

    # ================================================================== Kâğıt Fiyatlama (kagitfiyat.py)
    def kagit_fiyat(self, user: Optional[str], query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Kâğıt Fiyatlama: every fixed coupon bond and bill of the trading list - the fair yield (the neighbours' curve
        and OIS, each plus the bond's spread at the last close, weighted by maturity), the quote, the good levels, the
        market against them and how the price was built (:mod:`tto.kagitfiyat`); ``query["isin"]``: that bond alone
        (the card's block).  A request it cannot answer is a 400 with the reason in Turkish."""
        from .kagitfiyat import KagitError
        q = query or {}
        try:
            return self.kagitfiyat.view(user, q["isin"] if "isin" in q else None)
        except KagitError as exc:
            raise ServiceError(str(exc))

    def kagit_fiyat_widths(self, user: Optional[str], body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """The quote's width by maturity bucket - administrators only, every change logged."""
        from .kagitfiyat import KagitError
        try:
            return self.kagitfiyat.set_widths(user, body or {})
        except KagitError as exc:
            raise ServiceError(str(exc))

    # ================================================================== Kâğıt Fiyat Yükleme (fiyatyukleme.py)
    def fiyat_yukleme(self, user: Optional[str], what: str, body: Optional[Dict[str, Any]] = None) -> Any:
        """Kâğıt Fiyat Yükleme (:mod:`tto.fiyatyukleme`): ``what`` - "state" (the desk's list and its settings, the user's
        mode and text, the desk's labels; ``{"rev"}``: unchanged since that revision of the list - just that),
        "ekle" / "cikar" (the list), "sabit" / "sabit-sil" (a bond's fixed bid and ask: set or change / take off),
        "sabit-yapistir" (fixed prices pasted from Excel), "ayar"
        (mode, default and per bond spreads, a bond's Mid / Bid/Ask), "tanit" (the desk names an auction
        label's bond), "hesapla" (İhale / BBG), "cevir" (an edited cell's other half), "kaydet" (the file), "dosya" (a
        saved file again: bytes and name).  A request it cannot answer is a 400 with the reason in Turkish."""
        from .fiyatyukleme import FiyatError
        fy = self.fiyatyukleme
        b = body if isinstance(body, dict) else {}
        try:
            if what == "state":
                return fy.state(user, b.get("rev"))
            if what == "ekle":
                return fy.add(user, b.get("isins") if "isins" in b else b.get("isin"))
            if what == "cikar":
                return fy.remove(user, b.get("isin"))
            if what == "sabit":
                return fy.set_fixed(user, b)
            if what == "sabit-sil":
                return fy.remove_fixed(user, b.get("isin"))
            if what == "sabit-yapistir":
                return fy.paste_fixed(user, b.get("text"))
            if what == "ayar":
                return fy.set_options(user, b)
            if what == "tanit":
                return fy.name_label(user, b.get("label"), b.get("isin"))
            if what == "hesapla":
                return fy.calculate(user, b)
            if what == "cevir":
                return fy.convert(user, b)
            if what == "kaydet":
                return fy.save_file(user, b)
            if what == "dosya":
                return fy.saved_file(user, b.get("gun"))
        except FiyatError as exc:
            raise ServiceError(str(exc))
        raise ServiceError("bilinmeyen işlem: %s" % what, 404)

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

    # ================================================================== Prop (prop.py): the top bar's calculator and risk
    # To look at only: nothing is booked or sent; what cannot be worked out is a 400 with the reason in Turkish.
    def _prop(self, fn: Callable, *args: Any) -> Dict[str, Any]:
        from .prop import PropError
        try:
            return fn(*args)
        except PropError as exc:
            raise ServiceError(str(exc))

    def prop_state(self, user: Optional[str]) -> Dict[str, Any]:
        """What the Prop panel opens with: the desk's FX pairs that have a price (each with its mid), the user's limit."""
        return self._prop(self.prop.state, user)

    def prop_size(self, user: Optional[str], query: Optional[Dict[str, Any]] = None, lang: Optional[str] = None) -> Dict[str, Any]:
        """The calculator: ``pair``, ``stop``, ``loss`` (500k, 1mn), ``ccy`` (TRY / USD), ``entry`` (empty: the live mid) ->
        the direction, the size rounded down to 1M and the real loss at it (:func:`tto.prop.size`)."""
        return self._prop(self.prop.calc, user, query or {}, lang or self.settings.locale)

    def prop_risk(self, user: Optional[str], scope: Any = None) -> Dict[str, Any]:
        """The prop risk of a Trades tab (Kişisel by default, or Masa): the loss if every stop is hit, the tab's "Günlük"
        K/Z, the user's daily loss limit and the room left (:meth:`tto.prop.Prop.risk`)."""
        return self._prop(self.prop.risk, user, scope)

    def prop_limit(self, user: Optional[str]) -> Dict[str, Any]:
        key = self.require_user(user)
        return {"limit": self.prop.limit(key)}

    def prop_set_limit(self, user: Optional[str], amount: Any, ccy: Any, lang: Optional[str] = None) -> Dict[str, Any]:
        """The user's own daily loss limit (TRY or USD; empty: none) - nobody else sees or changes it."""
        return self._prop(self.prop.set_limit, user, amount, ccy, lang or self.settings.locale)

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

    def _mpc_implied(self, user: Optional[str], rows: List[Dict[str, Any]], board: Optional[List[Dict[str, Any]]] = None) -> None:
        """A meeting swap of one period - from a meeting to the next - next to the MPC OIS bootstrap: the step at its
        meeting that each of its levels stands for (``implied``, ``kind`` "mpc", bp) - the level's overnight
        equivalent − that of the bootstrap's rate for the period before the meeting (from the meeting before it, or
        from the OIS spot for the first one).  ``model``: the bootstrap's own step for the meeting.  The overnight
        equivalent is TLREF's as the MPC ima model compounds it - on business days, the period's weekend / holiday term
        the model's (:func:`tto.ppkcurve.window_overnight`, :meth:`OisMarket.mpc_term`; the desk, 25.11.2026: "B") -,
        EK_PPK's to the bp's last digit.  With the user's TLREF normalization on (OIS · PPK; :meth:`OisMarket.mpc_norm`)
        as EK_PPK has it then: every level taken to the normal path first (its period's stretch part off its ln G,
        :meth:`OisMarket.mpc_stretch`), the first meeting's base the normal TLREF (REF) - ``norm`` says so."""
        items = [(q, ("bid", "ask", "price")) for q in rows] + [(r, ("bid", "ask", "last", "best_bid", "best_ask")) for r in board or ()]
        items = [(q, f) for q, f in items if q.get("kind") == "mpc" and (q.get("mpc") or {}).get("start") and (q.get("mpc") or {}).get("meeting")]
        mkt = self._broker_market(user) if items else None
        if mkt is None:
            return
        try:
            table = mkt.mpc_table()
            days, spot = sorted(table["lndf"]), table["spot"]
            nm = mkt.mpc_norm() if spot is not None else None
        except Exception:  # noqa: BLE001 - a workbook without the table
            return

        def overnight(rate: float, a: float, b: float) -> Optional[float]:
            term = mkt.mpc_term(a, b)
            try:
                if term is None:
                    return None
                if nm is None:
                    return pk.window_overnight(rate, b - a, term)
                return pk.window_overnight(rate, b - a, term, mkt.mpc_stretch(nm, a, b))
            except (ValueError, OverflowError):
                return None

        for q, fields in items:
            s, e = self._serial(q["mpc"]["start"]), self._serial(q["mpc"]["end"])
            if s not in days or e not in days or days.index(s) == 0 or days.index(e) != days.index(s) + 1:
                continue                                    # several periods, or days the table does not have
            p = days[days.index(s) - 1]
            prev, model = mkt.mpc_span(p, s), mkt.mpc_span(s, e)
            first = p == spot                               # (the period before is the stub from the OIS spot)
            if nm is not None and first:
                base: Optional[float] = nm.ref              # (normalization on: the normal TLREF, not the stub's O/N)
            else:
                base = None if prev is None else overnight(prev, p, s)
            if base is None or prev is None:
                continue
            on_model = None if model is None else overnight(model, s, e)
            out: Dict[str, Any] = {"kind": "mpc", "meeting": q["mpc"]["meeting"], "days": e - s, "prev": prev * 100.0,
                                   "prev_on": base * 100.0, "prev_from": serial_to_date(p).isoformat(), "prev_to": q["mpc"]["start"],
                                   "model": None if on_model is None else (on_model - base) * 1e4,
                                   "model_level": None if model is None else model * 100.0}
            if nm is not None:
                # TLREF's normalization: the normalization date, the gap (bp), whether the base is the normal TLREF
                out["norm"] = {"date": serial_to_date(spot + nm.days).isoformat(), "gap": nm.gap * 1e4,
                               "ref": nm.ref * 100.0, "base_ref": first}
            for f in fields:
                if type(q.get(f)) is float:
                    on = overnight(q[f] / 100.0, s, e)
                    if on is not None:
                        out[f] = (on - base) * 1e4
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

    def edit_trade(self, user: str, trade_id: Any, payload: Any, lang: Optional[str] = None) -> Dict[str, Any]:
        """"Düzenle": a trade changed after it was entered - anyone's, by anyone, as a trade is deleted.  What the edit
        does not change does not move:

        * the counterparty and the note alone: those two and nothing else, on a trade of any day (``payload``
          ``{"fields": {"cpt", "note"}}``, or the form's that differs in them alone; ``priced``: "none");
        * an amount, a forward's side, a level, a size, a leg's own rate: struck again at the trade's own prices - a
          forward's forward, TRY rate and spot; an OIS's curve and its mid at the trade, the cost against that mid
          (:func:`blotter.restrike`); a bond's DV01 per nominal (``priced``: "trade");
        * another instrument - an OIS's side, tenors, months or days, a forward's pair, value date, pricing or the price
          typed, a bond's ISIN: priced on today's market as a new trade is (``priced``: "today", ``why``: what changed).

        A priced edit is a trade of today's only.  ``payload``: what the entry form sends for a new trade of the kind, with
        ``kind`` (the trade's own: another product is refused, so are an OIS's other strategy and number of legs - delete
        it and enter it again).  The rows change in place - the same ids (whatever links to them stays linked: the chat's
        pairs), day, who entered it and when; every leg keeps the edit (``edits``: when, by whom, ``priced`` and ``why``,
        the values before - the last ``bl.EDITS_KEPT``).  Returns the trade as the entry form's quote shows it, with
        ``ids``, ``priced``, ``why`` and ``edited`` (false: nothing changed, nothing written)."""
        user = self.require_user(user)
        res = self.et.call_at(EngineThread.WRITE, self._edit_trade, user, trade_id, payload, lang)
        if res["edited"]:
            self.bump()
        return res

    def edit_preview(self, user: str, trade_id: Any, payload: Any, lang: Optional[str] = None) -> Dict[str, Any]:
        """What "Değişikliği kaydet" would make of the edit form (:meth:`edit_trade`), nothing saved: ``priced``, ``why`` and
        ``quote`` - the trade as the form's quote shows it (an OIS against the mid its cost is counted on)."""
        user = self.require_user(user)
        return self.et.call(self._edit_trade, user, trade_id, payload, lang, True)

    #: the names of the products and the OIS strategies, in what an edit says
    _KIND_NAMES = {"fwd": "FX Forward", "ois": "OIS", "bond": "Tahvil"}
    _STRATEGY_NAMES = {"outright": "Outright", "spread": "Spread", "fly": "Fly", "fra": "FRA", "mpc": "MPC"}

    def _edit_trade(self, user, trade_id, payload, lang=None, dry=False) -> Dict[str, Any]:
        try:
            legs = self.store.trade_legs(int(trade_id))
        except (TypeError, ValueError):
            legs = []
        if not legs:
            raise ServiceError("işlem bulunamadı", 404)
        first, kind = legs[0], legs[0]["kind"]
        payload = dict(payload) if isinstance(payload, dict) else {}
        asked = str(payload.pop("kind", None) or kind)
        if asked != kind:
            raise ServiceError("düzenlemede ürün değişmez (%s → %s): strateji değişiyorsa silip yeniden girin"
                               % (self._KIND_NAMES.get(kind, kind), self._KIND_NAMES.get(asked, asked)))

        def priced_today() -> None:
            # a price, an amount or an instrument changes on a trade of today only; a day gone by: its counterparty and note
            if first["trade_date"] != self.today_iso():
                raise ServiceError("geçmiş günün işleminde yalnızca karşı taraf ve not değişir: bu işlem %s günü girildi"
                                   % _dt.date.fromisoformat(first["trade_date"]).strftime("%d.%m.%Y"))

        if isinstance(payload.get("fields"), dict):
            plan = self._edit_fields(kind, legs, payload["fields"])
        else:
            plan = {"fwd": self._edit_fwd, "ois": self._edit_ois, "bond": self._edit_bond}[kind](user, legs, payload, lang, priced_today)
        ids = [lg["id"] for lg in legs]
        head = {"id": ids[0], "ids": ids, "priced": plan["priced"], "why": plan["why"], "edited": False}
        if dry:
            return dict(head, quote=plan["quote"])
        out = dict(plan["quote"] or {}, **head)
        changes = [bl.edited(lg, rec) for lg, rec in zip(legs, plan["recs"])] if plan["priced"] else []
        if not any(before for _, before in changes):
            return out                                      # the same trade: nothing is written
        entry = {"at": now_iso(), "by": user, "priced": plan["priced"]}
        if plan["why"]:
            entry["why"] = plan["why"]
        items = [(lg["id"], dict(new, edits=(list(lg.get("edits") or []) + [dict(entry, was=before)])[-bl.EDITS_KEPT:]))
                 for lg, (new, before) in zip(legs, changes)]           # (a package's legs: one edit, each its own values)
        if not self.store.update_trades(items, user):
            raise ServiceError("işlem bulunamadı", 404)    # (deleted meanwhile)
        self._sync_blotter()
        out["edited"] = True
        return out

    @staticmethod
    def _edit_fields(kind: str, legs: List[Dict[str, Any]], fields: Dict[str, Any]) -> Dict[str, Any]:
        """The counterparty and the note of a trade alone - those sent (a bond has no counterparty); nothing is priced."""
        own = {k: str(fields.get(k) or "").strip()[:n] for k, n in (("cpt", 40), ("note", 200))
               if k in fields and (k != "cpt" or kind != "bond")}
        changed = any(v != (legs[0].get(k) or "") for k, v in own.items())
        return {"priced": "none" if changed else None, "why": [], "recs": [own] * len(legs), "quote": None}

    def _edit_fwd(self, user, legs, payload, lang, priced_today) -> Dict[str, Any]:
        """A forward edited from its form: another pair, value date, pricing or price typed (a pair without a curve: its
        spot) - priced on today's market; another side or amount - struck at its own rates (``bl.forward_restruck``);
        else its counterparty and note."""
        t = legs[0]
        p = self._fwd_payload(payload, lang)
        pair = str(t.get("pair") or "USDTRY").upper()
        basis = str(p.get("basis") or "RET_MID").upper()
        why = []
        if p["pair"] != pair:
            why.append("parite")
        if p.get("value_date") != t.get("value_date"):
            why.append("valör")
        if basis != str(t.get("basis") or "RET_MID").upper():
            why.append("fiyatlama")
        elif basis in ("TRY", "FWD", "SP") and not bl.same(p.get("manual"), t.get("manual")):
            why.append("fiyat")
        if p["pair"] == pair and pair not in ("USDTRY", "EURTRY") and type(p.get("spot")) is float \
                and not bl.same(p["spot"], t.get("spot")):
            why.append("spot")
        if why:
            priced_today()
            book = self._book("tto")
            try:
                rec = bl.forward_trade(book, self.interp.boot_overlay(user, book), p)
            except bl.TradeError as exc:
                raise ServiceError(str(exc))
            return {"priced": "today", "why": why, "recs": [rec], "quote": dict(self._quote_forward(user, payload, lang), dir=rec["dir"])}
        own = {"cpt": str(p.get("cpt") or "").strip()[:40], "note": str(p.get("note") or "").strip()[:200]}
        direction = str(p.get("dir") or "").upper()
        if direction not in ("B", "S"):
            raise ServiceError("yön B (alış) ya da S (satış) olmalı")
        try:
            typed = bl.typed_amount(p)
        except bl.TradeError as exc:
            raise ServiceError(str(exc))
        if typed is None:
            raise ServiceError("tutar pozitif bir sayı olmalı")
        kept = ("quote", t.get("typed_amount")) if t.get("typed") == "quote" else ("base", t.get("amount"))
        if direction != t.get("dir") or typed[0] != kept[0] or not bl.same(typed[1], kept[1]):
            priced_today()
            try:
                rec = dict(bl.forward_restruck(t, direction, typed), **own)
            except bl.TradeError as exc:
                raise ServiceError(str(exc))
            return {"priced": "trade", "why": [], "recs": [rec], "quote": self._fwd_quote(dict(t, **rec))}
        changed = any(v != (t.get(k) or "") for k, v in own.items())
        return {"priced": "none" if changed else None, "why": [], "recs": [own], "quote": self._fwd_quote(dict(t, **own))}

    @staticmethod
    def _fwd_quote(t: Dict[str, Any]) -> Dict[str, Any]:
        """The entry form's quote of a forward as it is kept - its own rates, no market of today (no curves beside it)."""
        pair = str(t.get("pair") or "USDTRY").upper()
        vd = t.get("value_date")
        quote_typed = t.get("typed") == "quote"
        return {"pair": pair, "base": pair[:3], "quote": pair[3:], "basis": t.get("basis"), "value_date": vd,
                "value_date_iso": serial_to_date(vd).isoformat() if type(vd) is float else None, "dir": t.get("dir"),
                "forward": t.get("forward"), "try_rate": t.get("try_rate"), "usd_rate": t.get("usd_rate"), "days": t.get("days"),
                "spot": t.get("spot"), "points": t.get("points"), "amount": t.get("amount"), "tl": t.get("tl"),
                "typed": "quote" if quote_typed else "base", "typed_amount": t.get("typed_amount") if quote_typed else t.get("amount"),
                "usdtry": t.get("usdtry"), "table": {}, "ret_bid": None, "ret_mid": None, "ret_ask": None,
                "dv01": {"tl": t.get("dv01_tl"), "usd": t.get("dv01"), "usd_leg": t.get("usd_dv01"), "amount": t.get("amount"),
                         "dir": t.get("dir")}}

    def _edit_ois(self, user, legs, payload, lang, priced_today) -> Dict[str, Any]:
        """An OIS edited from its form: another side, tenors, months or days - priced on today's market (its strategy and
        number of legs stay); another level, size or leg's own rate - struck on its own curve, its cost against its mid at
        the trade (``bl.restrike``); else its counterparty and note."""
        first = legs[0]
        p = self._ois_payload(payload, lang)
        strategy = str(p.get("strategy") or "outright").lower()
        was = str(first.get("strategy") or "outright")
        if strategy != was:
            raise ServiceError("düzenlemede strateji değişmez (%s → %s): strateji değişiyorsa silip yeniden girin"
                               % (self._STRATEGY_NAMES.get(was, was), self._STRATEGY_NAMES.get(strategy, strategy)))
        side = lambda s: str(s or "").upper().replace("GOVDE", "GÖVDE")           # noqa: E731
        why = []
        if side(p.get("side")) != side(first.get("side")):
            why.append("yön")
        if bl.typed_instrument(strategy, p) != bl.ois_instrument(strategy, legs):
            why.append({"fra": "FRA ayları", "mpc": "tarihler"}.get(strategy, "vade"))
        if why:
            priced_today()
            q, recs, _ = self._ois_records(user, payload, lang)
            if len(recs) != len(legs):
                raise ServiceError("düzenlemede bacak sayısı değişmez (%d → %d%s): strateji değişiyorsa silip yeniden girin"
                                   % (len(legs), len(recs), "; spot başlangıçlı FRA tek bacaktır" if strategy == "fra" else ""))
            place = {lg.get("role"): i for i, lg in enumerate(legs)}
            if len(place) == len(legs) and all(r["role"] in place for r in recs):
                recs.sort(key=lambda r: place[r["role"]])            # each leg into its own row
            return {"priced": "today", "why": why, "recs": recs, "quote": q}
        own = {"cpt": str(p.get("cpt") or "").strip()[:40], "note": str(p.get("note") or "").strip()[:200]}
        level = p.get("level")
        rates = {k: p[k + "_rate"] for k in ("short", "wing1", "wing2", "start") if type(p.get(k + "_rate")) is float}
        by_role = {lg.get("role"): lg for lg in legs}
        size = self._ois_sized(p)
        # the size the form gives back untouched (``keep_size``: a spread / fly sized by DV01 cannot say its legs' nominals)
        same_size = p.get("keep_size") is True or self._ois_same_size(strategy, legs, size)
        if not bl.same(level, first.get("level")) or not same_size \
                or any(k in by_role and not bl.same(v, by_role[k].get("rate")) for k, v in rates.items()):
            priced_today()
            mkt = self._ois_curve(user, self._book("tto"))
            try:
                q = bl.ois_legs(mkt, p)                               # (checked as a new trade is; its label)
                nominal = size[1] if not same_size and size[0] == "nominal" else None
                dv01 = None if same_size or size[0] == "nominal" else (size[1] if size[1] is not None else mkt.default_dv01)
                struck = bl.restrike(strategy, legs, level, rates, nominal, dv01, mkt.lot)
            except bl.TradeError as exc:
                raise ServiceError(str(exc))
            cost = bl.cost_vs_mid(strategy, first.get("side"), level, first.get("market"))
            common = dict(own, level=level, label=q["label"], cost_bp=cost,
                          cost_usd=None if cost is None else cost * bl.risk_dv01(strategy, struck))
            if not same_size:
                common["size_mode"], common["size_typed"] = size
            by_id = {lg["id"]: dict(common, rate=lg["rate"], nominal=lg["nominal"], dv01=lg["dv01"]) for lg in struck}
            recs = [by_id[lg["id"]] for lg in legs]
            return {"priced": "trade", "why": [], "recs": recs, "quote": self._ois_quote(user, legs, recs)}
        changed = any(v != (first.get(k) or "") for k, v in own.items())
        recs = [own] * len(legs)
        return {"priced": "none" if changed else None, "why": [], "recs": recs, "quote": self._ois_quote(user, legs, recs)}

    @staticmethod
    def _ois_same_size(strategy: str, legs: List[Dict[str, Any]], size: Tuple[str, Optional[float]]) -> bool:
        """Whether the size the edit form sends is the trade's: the nominal of its legs (a fly's wings half of it), or the
        DV01 it was entered with (none: the sheet's DV01, as then)."""
        mode, x = size
        if mode == "nominal":
            try:
                ordered = bl.legs_in_order(strategy, legs)
            except bl.TradeError:
                return False
            return all(bl.same(x * bl.leg_weight(strategy, lg.get("role")), lg.get("nominal")) for lg in ordered)
        return legs[0].get("size_mode") == "dv01" and bl.same(x, legs[0].get("size_typed"))

    def _ois_quote(self, user, legs: List[Dict[str, Any]], recs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """The entry form's quote of an OIS as an edit leaves it (``recs`` over its ``legs``): legs, level, label, its cost
        against the mid it is counted on - the TL at today's USDTRY."""
        rows = [dict(lg, **rec) for lg, rec in zip(legs, recs)]
        first = rows[0]
        try:
            usdtry: Optional[float] = self._ois_curve(user, self._book("tto")).usdtry
        except bl.TradeError:
            usdtry = None
        cost_usd = first.get("cost_usd")
        dv01 = [(lg["dv01"], lg.get("dir")) for lg in rows if type(lg.get("dv01")) is float]
        return {"strategy": first.get("strategy"), "side": first.get("side"), "level": first.get("level"), "label": first.get("label"),
                "legs": [{k: lg.get(k) for k in ("tenor", "dir", "rate", "nominal", "dv01", "role", "cpt")} for lg in rows],
                "info": {"market": first.get("market"), "cost_bp": first.get("cost_bp"), "cost_usd": cost_usd,
                         "cost_tl": cost_usd * usdtry if type(cost_usd) is float and type(usdtry) is float else None},
                "usdtry": usdtry, "dv01": {"net": sum(d if s == "B" else -d for d, s in dv01), "gross": sum(d for d, _ in dv01)}}

    def _edit_bond(self, user, legs, payload, lang, priced_today) -> Dict[str, Any]:
        """A bond edited from its form: another ISIN - priced again (its DV01 from today's DİBS RV table); another side,
        amount or price - its DV01 per nominal as it was; else its note."""
        t = legs[0]
        inst, amount, price = self._bond_checked(payload, lang)
        note = str(payload.get("note") or "").strip()[:200]
        isin = lambda s: "".join(str(s or "").split()).upper()                # noqa: E731
        if isin(inst) != isin(t.get("instrument")):
            priced_today()
            rec = self._bond_record(user, payload, lang)
            return {"priced": "today", "why": ["enstrüman"], "recs": [rec], "quote": self._bond_quote(user, dict(t, **rec))}
        if not bl.same(amount, t.get("amount")) or not bl.same(price, t.get("price")):
            priced_today()
            k = amount / t["amount"]                                  # (a bond's DV01: linear in its nominal)
            rec = {"amount": amount, "price": price, "note": note,
                   "dv01_tl": t["dv01_tl"] * k if type(t.get("dv01_tl")) is float else None,
                   "dv01": t["dv01"] * k if type(t.get("dv01")) is float else None}
            return {"priced": "trade", "why": [], "recs": [rec], "quote": self._bond_quote(user, dict(t, **rec))}
        changed = note != (t.get("note") or "")
        return {"priced": "none" if changed else None, "why": [], "recs": [{"note": note}], "quote": self._bond_quote(user, dict(t, note=note))}

    def _bond_quote(self, user, t: Dict[str, Any]) -> Dict[str, Any]:
        """The entry form's quote of a bond as an edit leaves it: what the DİBS RV table says of the paper, its own DV01."""
        q = self._bond_risk(user, t.get("instrument") or "", t.get("amount"))
        q.update({"instrument": t.get("instrument"), "amount": t.get("amount"), "per": t.get("amount"), "price": t.get("price"),
                  "dv01_tl": t.get("dv01_tl"), "dv01": t.get("dv01")})
        return q

    def trade_prefill(self, user: Optional[str], payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        """"İşlem gir" on a price cell of a page (its table's ``"trade"`` hint, :mod:`tto.tradehint`):
        ``{"spec": …}``, what Günlük İşlemler's form is filled with - the instrument and the dates read from the
        clicked row's own cells as ``user`` sees them, the price as it was on screen (``text``), the side from the
        column.  ``payload``: ``{"view", "panel", "row", "col", "text", "label"}`` (``row``: the sheet's row number,
        ``col``: the column's letters, ``label``: the cell's name on screen, for the trade's note).  Nothing is
        saved."""
        return self.et.call(self._trade_prefill, user, payload, lang or self.settings.locale)

    def _trade_prefill(self, user, payload, lang) -> Dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        v = self.view_index.get(payload.get("view")) if isinstance(payload.get("view"), str) else None
        p = next((x for x in v["panels"] if x.get("id") == payload.get("panel")), None) if v else None
        if p is None or not (p.get("trade") or {}).get("cells"):
            raise ServiceError("bu tablonun fiyatları işlem olarak girilmez", 404)
        if v.get("admin") and user is not None and not self._is_admin(user):
            raise ServiceError("bu sayfa yalnızca yöneticilere açıktır", 403)
        row, col, text = payload.get("row"), payload.get("col"), payload.get("text")
        if isinstance(row, bool) or not isinstance(row, int) or not isinstance(col, str) or not isinstance(text, str):
            raise ServiceError("hücre ve fiyat gerekli")
        book = self.books[v["book"]]
        sheet = p.get("sheet", v.get("sheet"))
        calc = self._calc(user_key(user) if user else None, book)

        def read(ref: str) -> Any:
            si, rc = book.cell(ref if "!" in ref else "%s!%s" % (sheet, ref))
            return calc.get(si, *divmod(rc, COLS))

        label = " ".join(str(payload.get("label") or "").split())[:80]
        where = " · ".join(x for x in (v.get("title"), str(p.get("title") or "").split("  ·  ")[0].strip()) if x)
        try:
            spec = th.prefill(p["trade"], row, col, text, read, self._tenor_date, lang,
                              note="Fiyat: %s(%s)" % (label + " " if label else "", where))
        except (th.HintError, bl.TradeError) as exc:
            raise ServiceError(str(exc))
        return {"spec": spec}


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


def _freeze_columns(data: Optional[Dict[str, Any]], n: Any, hidden: Optional[Callable[[str], bool]] = None) -> None:
    """A view's ``"freeze": n`` on its table: the first n columns as the panel shows them stay in view while it scrolls
    sideways (``fz``, grid.js) - in place of the workbook's frozen panes; ``0``: none (the desk, 27.11.2026: the name or
    ISIN of a wide table in sight).  ``hidden``: whether a column of the sheet is one Excel hides - shown as well
    ("Yardımcı tablolar"), it is not counted, so that n names the same columns either way.  Nothing to scroll past (n
    reaches the last column): none."""
    if not isinstance(data, dict) or not data.get("rows") or isinstance(n, bool) or not isinstance(n, int):
        return
    data.pop("fz", None)
    width = len(data["rows"][0])
    cols = data.get("c") or []
    k = seen = 0
    while k < width and seen < n:
        letter = cols[k] if k < len(cols) else None
        if not (hidden is not None and isinstance(letter, str) and _COL_LETTERS.match(letter) and hidden(letter)):
            seen += 1
        k += 1
    if 0 < k < width:
        data["fz"] = k


_COL_LETTERS = re.compile(r"^[A-Z]{1,3}$")


def _pick_columns(data: Dict[str, Any], cols: Sequence[str]) -> None:
    """A table's columns in the order a page wants them (``["A", "B", "D", "M", ...]`` by column letter; one the
    table does not have - left out as empty, hidden - is skipped, one not named is not shown).  Every cell keeps its
    column letter, so an input is still typed into its own cell.  A span across columns (a merged cell: ÇAPRAZ FORWARD's
    "Yöntem" row) keeps the columns it covered that still follow it, in their order; a cell it covered that it no longer
    reaches is a cell of its own again (empty) - so a row keeps all of its columns.  The columns Excel keeps in view
    (``fz``) stay so when the order keeps them all first, in their place (DİBS RV's ISIN, source and name with its O/N
    columns beside the yields); otherwise none."""
    have = data.get("c") or []
    order = [have.index(c) for c in cols if c in have]
    if not order or order == list(range(len(have))):
        return
    at = {j: k for k, j in enumerate(order)}            # a column of the table -> its place in the order asked for
    rows = data["rows"]
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            cs = cell.get("cs", 1) if isinstance(cell, dict) else 1
            if cs <= 1 or cell.get("sk"):
                continue
            n = 1                                         # the columns of the span that still follow the cell, itself first
            while j in at and n < cs and at.get(j + n) == at[j] + n:
                n += 1
            if n > 1:
                cell["cs"] = n
            else:
                cell.pop("cs", None)
            for ii in range(i, min(i + cell.get("rs", 1), len(rows))):
                for jj in range(j + n, min(j + cs, len(rows[ii]))):
                    if isinstance(rows[ii][jj], dict):
                        rows[ii][jj].pop("sk", None)
    data["rows"] = [[row[j] for j in order] for row in rows]
    data["c"] = [have[j] for j in order]
    fz = data.pop("fz", None)                    # (frozen columns counted the sheet's order)
    if fz and order[:fz] == list(range(fz)) and fz < len(order):
        data["fz"] = fz


def _pick_rows(data: Dict[str, Any], rows: Sequence[int]) -> None:
    """A table's rows in the order a page wants them (``[19, 25, 26]`` by the sheet's row number; one the table does not
    have - left out as empty - is skipped, one not named is not shown): the twin of :func:`_pick_columns` (the desk,
    28.11.2026: B15 - VİOP's four contract tables repeated five rows each).  Every cell keeps its row number, so an input
    is still typed into its own cell.  A cell merged down over rows keeps the rows of it that still follow it, in order;
    a cell it covered that it no longer reaches is a cell of its own again (empty).  ``ar``: every row the range has, so
    that a block pasted lands on the rows on screen (grid.js ``ownLayout``)."""
    have = data.get("r") or []
    src = data.get("rows") or []
    order = []
    for r in rows:
        if r in have and have.index(r) not in order:
            order.append(have.index(r))
    if not order or order == list(range(len(have))):
        return
    at = {i: k for k, i in enumerate(order)}            # a row of the table -> its place in the order asked for
    for i, row in enumerate(src):
        for j, cell in enumerate(row):
            rs = cell.get("rs", 1) if isinstance(cell, dict) else 1
            if rs <= 1 or cell.get("sk"):
                continue
            n = 1                                         # the rows of the span that still follow the cell, itself first
            while i in at and n < rs and at.get(i + n) == at[i] + n:
                n += 1
            if n > 1:
                cell["rs"] = n
            else:
                cell.pop("rs", None)
            for ii in range(i + n, min(i + rs, len(src))):
                for jj in range(j, min(j + cell.get("cs", 1), len(src[ii]))):
                    if isinstance(src[ii][jj], dict):
                        src[ii][jj].pop("sk", None)
    data["ar"] = data.get("ar") or list(have)
    data["rows"] = [src[i] for i in order]
    data["r"] = [have[i] for i in order]


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
    table = entry.get("type") in ("table", "notes") and isinstance(entry.get("data"), dict)
    if (r["rows"] or r["cols"]) and table:
        entry = dict(entry, data=_pick_part(entry["data"], r["rows"], r["cols"]))
    tab = ""
    for sec in res.get("sections") or []:
        if r["panel"] in sec.get("panels", []):
            tab = sec.get("title") or ""
            break
    out = dict(base, entry=entry, book=res.get("book"), page=res.get("title"), tab=tab)
    if r.get("keys") and table:
        out["rk"] = _row_keys(entry["data"], bool(entry.get("ranked")))      # (the picker of a launchpad item's rows)
    return out


#: a date written as text ("4.11.2026", "2026-11-04", a time after it): Bloomberg's settle dates, a contract's expiry
_DATE_TEXT = re.compile(r"^(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})(\s+\d{1,2}:\d{2}(:\d{2})?)?$")
#: what follows it in a row's name is a detail that changes while the row stays what it is
_DETAIL = " · "


def _row_text(row: List[Dict[str, Any]]) -> Optional[str]:
    """A row's first text from the left, as it reads (an earlier version kept a launchpad's rows by it)."""
    for c in row:
        if not isinstance(c, dict) or c.get("sk") or c.get("k") != "s":
            continue
        t = " ".join(str(c.get("t") or "").split())
        if t:
            return t
    return None


def _row_name(row: List[Dict[str, Any]]) -> Optional[str]:
    """The name of a row: its first text from the left - a tenor, an ISIN, a pair (numbers and dates before it are
    passed over: the RET table's day count stands left of its tenor; so is a date written as text, a settle date that
    moves every day; so is a button - the trading summary's ★ left of its bond).  ``None``: the row has no such text."""
    for c in row:
        if not isinstance(c, dict) or c.get("sk") or c.get("k") != "s" or "act" in str(c.get("cls") or "").split():
            continue
        t = " ".join(str(c.get("t") or "").split())
        if t and not _DATE_TEXT.match(t):
            return t
    return None


def _stem(name: str) -> str:
    """A name up to its first " · ": the part that stays ("MPC1→2 · 1.2–2.6A" - the months to the meetings count down
    every day; "MPC1 / MPC2 · REC k+1 / PAY k" - the direction follows the market)."""
    return name.split(_DETAIL, 1)[0].strip() or name


def _row_label(row: List[Dict[str, Any]]) -> Optional[str]:
    """What a launchpad keeps a row by when its name is the table's only one of its kind: the name's stable part."""
    name = _row_name(row)
    return _stem(name) if name else None


def _row_keys(data: Dict[str, Any], ranked: bool = False) -> List[Any]:
    """How a launchpad's choice of rows keeps each row of a table: its name's stable part (:func:`_row_label`) when no
    other row has it, else its whole name when no other row has that, else its number in the sheet; every row of a
    ranking by its number (the k-th best is what the row is, whatever fills it).  ``None``: a caption row (always
    shown)."""
    src = data.get("rows") or []
    nums = list(data.get("r") or [])
    heads = _caption_rows(src, nums) | _group_heads(src)
    names = [None if i in heads else _row_name(row) for i, row in enumerate(src)]
    stems = [_stem(n) if n else None for n in names]
    count_n: Dict[str, int] = {}
    count_s: Dict[str, int] = {}
    for n, s in zip(names, stems):
        if n:
            count_n[n] = count_n.get(n, 0) + 1
            count_s[s] = count_s.get(s, 0) + 1
    out: List[Any] = []
    for i in range(len(src)):
        if i in heads:
            out.append(None)
        elif not ranked and stems[i] and count_s[stems[i]] == 1:
            out.append(stems[i])
        elif not ranked and names[i] and count_n[names[i]] == 1:
            out.append(names[i])
        else:
            out.append(nums[i] if i < len(nums) else None)
    return out


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


def _group_heads(rows: List[List[Dict[str, Any]]]) -> set:
    """The captions of the groups of a list of bonds shown as the trading list has them ("Bono · 2 kâğıt": ``grp``,
    :meth:`Service._bond_rows`): rows of the page only - no row a launchpad box picks, keeps or shows."""
    return {i for i, row in enumerate(rows) if row and isinstance(row[0], dict) and row[0].get("grp")}


def _caption_rows(rows: List[List[Dict[str, Any]]], nums: List[Any]) -> set:
    """The rows at the top of a table that name its columns (a lone title row above them too): a part of the table
    keeps them.  A group's caption of a list of bonds (:func:`_group_heads`) is none of them and does not count: the
    table's own header is found as it was before the groups."""
    grp = _group_heads(rows)
    out = set(i for i, r in enumerate(nums) if r == 0 and i not in grp)
    for i, row in enumerate(rows):
        if i in out or i in grp:
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

    ``rows``: each a row's key (:func:`_row_keys`: its name, or its number in the sheet) - or, as an earlier version
    kept it, its whole first text (a name whose detail after " · " changed since is still found by its stable part);
    the caption rows at the top always stay.  ``cols``: column letters.  Both keep the table's own order.  A merged cell
    keeps the part of it that is still there; when its first cell went, what it shows moves to the first one left (read
    only then: typing there would write another cell).  Nothing of either left: the whole table, marked
    ``part_missing``.  A part says which rows / columns the whole table has (``ar`` / ``ac``): the browser tells a
    gap the part made from one of the sheet's own (hidden in Excel, or empty) when a block is pasted or pointed at."""
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
        grp = _group_heads(src)
        body = {i for i in range(len(src)) if i not in heads and i not in grp and i < len(nums) and nums[i] in numbers}
        if labels:
            keys = _row_keys(data)
            texts = [_row_text(row) for row in src]
            for x in labels:
                hit = [i for i in range(len(src)) if i not in heads and i not in grp and (keys[i] == x or texts[i] == x)]
                if not hit and _DETAIL in x:
                    hit = [i for i in range(len(src)) if keys[i] == _stem(x)]
                    hit = hit if len(hit) == 1 else []
                body.update(hit)
        if body:
            keep_r = sorted(heads | body)
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
        if len(keep_r) < len(src):
            out["ar"] = data.get("ar") or nums           # (a table whose page shows some of its rows: all of the range's)
    if letters:
        out["c"] = [letters[j] for j in keep_c if j < len(letters)]
        if len(keep_c) < width:
            out["ac"] = letters
    fz = data.get("fz") or 0
    if fz:
        n = sum(1 for j in keep_c if j < fz)
        if 0 < n < len(keep_c):
            out["fz"] = n
    if missing:
        out["part_missing"] = True
    return out


def _cell_tips(data: Optional[Dict[str, Any]], book: Book, calc: Calc, sheet: str, tips: Dict[str, str]) -> None:
    """Tooltips a table's cells take from the workbook (``{"W": "AA"}``: the text in column AA of a cell's row is the
    tooltip of the table's cell in column W - which curve a rate comes from, say; an empty text gives none).  The column
    the texts are in need not be shown."""
    letters = (data or {}).get("c")
    if not letters:
        return
    si = book.model.sheet_index[sheet]
    for col, src in tips.items():
        if col not in letters:
            continue
        j, c = letters.index(col), col_to_index(src)
        for i, r in enumerate(data.get("r") or []):
            cell = data["rows"][i][j]
            if not r or not isinstance(cell, dict) or cell.get("sk"):
                continue
            text = calc.get(si, r, c)
            if isinstance(text, str) and text.strip():
                cell["tip"] = cell["tip"] + "\n" + text.strip() if cell.get("tip") else text.strip()


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
