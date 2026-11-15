"""Application service: everything the web layer needs, independent of HTTP.

One dedicated engine thread (large stack, serialises all calculation work) owns the workbook engines.
The service keeps per-user input overlays, the shared desk inputs (RET curve, calendars, blotter) and a
generation counter that increases whenever something visible may have changed.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import json
import math
import os
import queue
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote as _quote

from . import auth
from . import blotter as bl
from . import brokerchat as bc
from . import extras as ex
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
from .xl.engine import Calc, Clock
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
    def __init__(self, message: str, status: int = 400):
        Exception.__init__(self, message)
        self.status = status


class EngineThread(object):
    """Runs every calculation on one thread with a large stack (formula chains recurse deeply)."""

    def __init__(self, name: str = "tto-engine"):
        self._q: "queue.Queue" = queue.Queue()
        old = threading.stack_size()
        try:
            threading.stack_size(256 * 1024 * 1024)
        except (ValueError, RuntimeError):
            pass
        self._t = threading.Thread(target=self._loop, name=name, daemon=True)
        self._t.start()
        try:
            threading.stack_size(old)
        except (ValueError, RuntimeError):
            pass

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            fut, fn, args, kw = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn(*args, **kw))
            except BaseException as exc:  # noqa: BLE001 - delivered to the caller
                fut.set_exception(exc)

    def submit(self, fn: Callable, *args, **kw) -> "concurrent.futures.Future":
        fut: "concurrent.futures.Future" = concurrent.futures.Future()
        self._q.put((fut, fn, args, kw))
        return fut

    def call(self, fn: Callable, *args, **kw):
        if threading.current_thread() is self._t:
            return fn(*args, **kw)
        return self.submit(fn, *args, **kw).result()

    def stop(self) -> None:
        self._q.put(None)


_DUMMY: List[str] = []


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
        self.store = store or Store(self.settings.db_path)
        self.et = EngineThread()
        self.gen = 1
        self._gen_lock = threading.Lock()
        self._auth_lock = threading.Lock()               # account changes one at a time (two first administrators ...)
        self._hash_slots = threading.BoundedSemaphore(auth.HASH_SLOTS)    # password checks at a time
        self._listeners: List[Callable[[int], None]] = []
        self._overlays: Dict[Tuple[str, str], Dict[Tuple[int, int], Any]] = {}
        self._retired: Dict[str, set] = {}
        self._view_cache: Dict[Tuple, Dict[str, Any]] = {}
        # live: when the dashboard saw each security trade today (its last price changed or its volume grew)
        self._trades_day = ""
        self._trades_seen: Dict[str, Dict[str, Any]] = {}
        self._trade_last: Dict[Tuple[str, str], float] = {}
        self._stop = threading.Event()
        self._market_thread: Optional[threading.Thread] = None
        self.started_at = time.time()
        self.et.call(self._setup, provider)
        from .history import History
        self.history = History(self)
        # the watch lists and the alarms: read again whenever the market or an input moved
        from .watch import Watch
        self.watch = Watch(self)
        # Spot / FX and FX vol: the option market's quotes of a pair, its smile and distribution, the vol monitor
        from .fx import Fx
        self.fx = Fx(self)
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
        self._sync_blotter()

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
                                                     blpapi_name=stand_in, **common)
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
        provider.start()
        favour_reader()
        return provider

    # ================================================================== lifecycle / events
    def start(self) -> None:
        if self._market_thread is None:
            self._market_thread = threading.Thread(target=self._market_loop, name="tto-market", daemon=True)
            self._market_thread.start()
            if self.mode == "live":
                threading.Thread(target=self._warmup_safe, name="tto-warmup", daemon=True).start()
            self.history.start()

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
            self.et.call(self._apply_market, keys)
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
        self.history._stop.set()                   # no new work while the provider goes down
        self.history._kick.set()
        self.fx.stop()
        try:
            stop = getattr(self.provider, "stop", None)
            if stop:
                stop()
        finally:
            try:
                self.history.stop()
            finally:
                self.et.stop()

    #: how often the running dashboard looks whether a meeting has passed: the OIS spot (Bloomberg's settle date) moves
    #: some time after midnight, not at the turn of the day
    ROLL_CHECK_SECONDS = 600.0

    def _market_loop(self) -> None:
        last_day = None
        last_roll = 0.0
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
                    changed = self.et.call(self._apply_market, keys)
                    if changed or day_changed:
                        if day_changed:
                            self.et.call(self._sync_blotter)
                        self.bump()
                if first or day_changed or time.monotonic() - last_roll >= self.ROLL_CHECK_SECONDS:
                    # a meeting that passed leaves the list by itself: MPC1 is always the next meeting
                    last_roll = time.monotonic()
                    self.history.auto_roll()
            except Exception:  # noqa: BLE001 - the loop must survive anything
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
        while not self._stop.is_set():
            self._watch_kick.wait(3.0)
            self._watch_kick.clear()
            if self._stop.is_set():
                break
            try:
                fired = self.et.submit(self.watch.tick).result(timeout=60)
            except Exception:  # noqa: BLE001 - the loop must survive anything (and a calculation thread gone)
                continue
            if fired:
                self.bump()

    def bump(self) -> int:
        kick = getattr(self, "_watch_kick", None)
        if kick is not None:
            kick.set()
        with self._gen_lock:
            self.gen += 1
            g = self.gen
            self._view_cache.clear()
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(g)
            except Exception:  # noqa: BLE001
                pass
        return g

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
            if action == "password":
                self._admin_password(me, data or {}, token)
            else:
                fn(me, data or {})
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
            for ref in fresh:
                book.declare(ref, scope="user", group="adhoc")
            self._overlays[key] = ov
            if ov:
                book.engine.set_user_inputs(user, ov)
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
        if not ov:
            return book.engine.shared
        return book.engine.user(user)

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
        ret = None
        if tto is not None:
            cells = ["Forward!%s%d" % (col, RET_FIRST_ROW + i) for i in range(len(RET_TENORS)) for col in ("W", "X")]
            ret = self.store.shared_meta("tto", cells)
        return {"mode": self.mode, "note": self.mode_note, "provider": prov, "gen": self.gen, "today": today,
                "ret": ret, "server_date": _dt.date.today().isoformat(),
                "books": {bid: {"title": b.title, "formulas": b.model.formula_count(),
                                "source": b.model.meta.get("source"), "left_out": list(getattr(b, "left_out", []))}
                          for bid, b in self.books.items()},
                "port": self.settings.port}

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
        return pages

    # ================================================================== rendering
    def view(self, user: Optional[str], view_id: str, show_hidden: bool = False, locale: Optional[str] = None) -> Dict[str, Any]:
        key = (user, view_id, show_hidden, locale, self.gen)
        hit = self._view_cache.get(key)
        if hit is not None:
            return hit
        out = self.et.call(self._view, user, view_id, show_hidden, locale)
        if len(self._view_cache) > 64:
            self._view_cache.clear()
        if out.get("gen") == self.gen:
            self._view_cache[key] = out
        return out

    def _view(self, user, view_id, show_hidden, locale) -> Dict[str, Any]:
        v = self.view_index.get(view_id)
        if v is None:
            raise ServiceError("sayfa bulunamadı: %s" % view_id, 404)
        if v.get("admin") and user is not None and not self._is_admin(user):
            raise ServiceError("bu sayfa yalnızca yöneticilere açıktır", 403)
        book = self.books[v["book"]]
        loc = numfmt.get_locale(locale or self.settings.locale)
        calc = self._calc(user, book)
        overlay = self._overlay(user, book) if user else None
        R = self.renderers[book.id]
        explorer = self._is_admin(user)                    # the sheet explorer is theirs
        gen = self.gen
        panels = []
        sheet_default = v.get("sheet")
        charts = list(book.model.sheets[book.model.sheet_index[sheet_default]].charts) if sheet_default else []
        used_charts = set()
        t0 = time.time()
        for p in v["panels"]:
            if p.get("hidden") and not show_hidden:
                continue
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
            sheet = p.get("sheet", sheet_default)
            if sheet is not None and sheet not in book.model.sheet_index:
                continue                               # a table of the dashboard's own that does not fit this file
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
                    if p.get("lift", True):
                        own = _lift_title(entry["data"])
                        if own and not p.get("keep_title"):
                            entry["title"] = own
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
                elif p["type"] == "chart":
                    spec = p.get("spec")
                    if spec is None:
                        idx = p.get("chart", 0)
                        if idx < len(charts):
                            used_charts.add(idx)
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
            panels.append(entry)
        if not any(p["type"] == "chart" for p in v["panels"]):
            for i, ch in enumerate(charts):
                try:
                    data = R.chart(calc, ch, loc)
                except Exception as exc:  # noqa: BLE001
                    continue
                panels.append({"id": "chart%d" % i, "type": "chart", "title": data["title"], "data": data,
                               "anchor": ch["anchor"], "hidden": False, "wide": False})
        sheet_obj = book.model.sheets[book.model.sheet_index[sheet_default]] if sheet_default else None
        if sheet_obj is not None:
            # pictures pasted on the sheet come after the tables
            for i, img in enumerate(sheet_obj.images):
                panels.append({"id": "image%d" % i, "type": "image", "title": v.get("image_titles", {}).get(str(i)) or "Excel'deki resim",
                               "src": "/api/image?book=%s&sheet=%s&i=%d" % (book.id, _quote(sheet_default), i),
                               "width": img.get("width"), "height": img.get("height"), "hidden": False, "wide": True})
        if show_hidden:
            # scratch cells that belong to no table: listed, so that nothing the workbook computes is missing
            for k, (sheet_name, rest) in enumerate(self._leftover_cells(v)):
                extra = "" if sheet_name == sheet_default else " (%s)" % sheet_name
                panels.append({"id": "rest" if k == 0 else "rest%d" % k, "type": "table",
                               "title": "Diğer hücreler · tablolara girmeyen formül ve değerler" + extra,
                               "hidden": True, "wide": False, "collapsed": False, "note": None,
                               "data": R.cells_table(calc, sheet_name, rest, loc, overlay)})
        note = v.get("note")
        if v.get("replay_note") and self.mode != "live" and not getattr(book, "recorded", True):
            note = v["replay_note"]                    # the workbook was saved without market data
        out = {"id": v["id"], "title": v["title"], "book": book.id, "sheet": sheet_default, "gen": gen,
               "panels": panels, "ms": int((time.time() - t0) * 1000), "note": note}
        out.update(view_layout(v, [p["id"] for p in panels]))
        hidden = self._hidden_pages(user)
        links = [link for link in self._shortcuts(v) if link["page"] not in hidden]      # (an administrators' page: theirs)
        if links:
            out["links"] = links
        return out

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

    def header(self, user: Optional[str], locale: Optional[str] = None) -> Dict[str, Any]:
        """Top strip: spot / TLREF / spot date ... read from MASA row 1-2 (labels) and its status row."""
        return self.et.call(self._header, user, locale)

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
        return {"ref": book.ref(si, rc), "formula": formula_text(book, si, rc), "cell": cell,
                "input": None if d is None else {"scope": d.scope, "label": d.label, "kind": d.kind},
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
    #: the TR holidays are kept twice: the TRY workbook's list (date and name; every WORKDAY of the workbook reads it)
    #: and the ASW workbook's (dates).  The settings page edits them as one list; the USD workbook's US holidays and
    #: FOMC meetings are shown beside it.  (book, sheet, first row, last row, date column, name column or None)
    HOLIDAY_LISTS = (("tto", "Motor", 361, 523, "A", "B"), ("asw", "ASW", 2, 200, "LR", None))
    HOLIDAYS_US = ("sofr", "SOFR_FOMC!BO4:BO70")
    FOMC_DATES = ("sofr", "SOFR_FOMC!B74:B83")

    def holidays(self) -> Dict[str, Any]:
        """``{"tr": [{"date", "name"}], "us": [iso], "fomc": [iso], "slots", "books"}`` - the TR list is the dates of both
        workbooks (a name from the TRY one)."""
        return self.et.call(self._holidays)

    def _holiday_cells(self) -> List[Tuple[Book, List[Tuple[Tuple[int, int], Optional[Tuple[int, int]]]]]]:
        """The TR holiday lists that are loaded: (book, [(date cell, name cell or None), ...])."""
        out = []
        for book_id, sheet, r1, r2, dcol, ncol in self.HOLIDAY_LISTS:
            book = self.books.get(book_id)
            if book is None or sheet not in book.model.sheet_index:
                continue
            si = book.model.sheet_index[sheet]
            dc = parse_a1(dcol + "1") % COLS
            nc = parse_a1(ncol + "1") % COLS if ncol else None
            out.append((book, [((si, r * COLS + dc), (si, r * COLS + nc) if nc is not None else None) for r in range(r1, r2 + 1)]))
        return out

    def _holidays(self) -> Dict[str, Any]:
        days: Dict[str, str] = {}
        lists = self._holiday_cells()
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

        return {"available": bool(lists), "tr": [{"date": d, "name": days[d]} for d in sorted(days)],
                "us": dates(self.HOLIDAYS_US), "fomc": dates(self.FOMC_DATES),
                "slots": min((len(cells) for _, cells in lists), default=0), "books": [b.id for b, _ in lists], "gen": self.gen}

    def set_holidays(self, user: str, items: List[Any]) -> Dict[str, Any]:
        """The TR holidays, for everybody: ``[{"date": "29.10.2026", "name": "Cumhuriyet"}, ...]`` (a date as text or a
        serial; a day given twice once).  Written to both workbooks, in date order; the rows below stay empty."""
        user = self.require_user(user)
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
        res = self.et.call(self._set_holidays, user, days)
        self.bump()
        res["gen"] = self.gen
        return res

    def _set_holidays(self, user: str, days: Dict[str, str]) -> Dict[str, Any]:
        lists = self._holiday_cells()
        if not lists:
            raise ServiceError("tatil listesi bu dosyalarda yok", 404)
        dates = sorted(days)
        room = min(len(cells) for _, cells in lists)
        if len(dates) > room:
            raise ServiceError("en çok %d tatil yazılabilir (%d verildi)" % (room, len(dates)))
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
        out = self._holidays()
        out["saved"] = len(dates)
        return out

    def set_inputs(self, user: str, book_id: str, items: List[Dict[str, Any]], allow_adhoc: bool = False,
                   lang: Optional[str] = None, lenient: bool = False) -> Dict[str, Any]:
        """items: [{"ref": "Forward!D2", "value": "03.12.2026"} ...] (value None / "" clears).

        ``lang`` is the number format the texts were typed / copied in ("tr": 1.234,56 – "en": 1,234.56).
        ``lenient`` (a block pasted from Excel): cells that are not inputs are skipped and counted, not errors.
        """
        user = self.require_user(user)
        res = self.et.call(self._set_inputs, user, book_id, items, allow_adhoc, lang or self.settings.locale, lenient)
        self.bump()
        res["gen"] = self.gen
        return res

    def _set_inputs(self, user, book_id, items, allow_adhoc, lang="tr", lenient=False) -> Dict[str, Any]:
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
        # a drop-down list Excel reads from a range (VİOP target's contracts, L97:X97) holds what those cells hold now
        calc = self._calc(user, book)
        for it in items:
            ref = it.get("ref")
            try:
                si, rc = book.cell(ref)
            except (KeyError, ValueError, AttributeError):
                errors.append("%s: hücre bulunamadı" % ref)
                continue
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
            self.store.set_shared_inputs(book.id, {book.ref(si, rc): _to_json(v) for (si, rc), v in shared_vals.items()}, user)
            if any(book.inputs[k].group == "ret" for k in shared_vals):
                self.store.add_ret_history(user, self._ret_rows(book))
        if user_vals or user_clear:
            ov = dict(self._overlay(user, book))
            ov.update(user_vals)
            for k in user_clear:
                ov.pop(k, None)
            self._overlays[(user, book.id)] = ov
            book.engine.set_user_inputs(user, ov)
            if user_vals:
                self.store.set_user_inputs(user, book.id, {book.ref(si, rc): _to_json(v) for (si, rc), v in user_vals.items()})
            if user_clear:
                self.store.clear_user_inputs(user, book.id, [book.ref(si, rc) for si, rc in user_clear])
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
        res = self.et.call(self._reset_inputs, user, book_id, refs, shared)
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
        return {"reset": n}

    def my_inputs(self, user: str) -> Dict[str, Any]:
        user = self.require_user(user)
        out = []
        for (bid, ref), val in sorted(self.store.user_inputs(user).items()):
            book = self.books.get(bid)
            label = ""
            if book is not None:
                try:
                    cell = book.cell(ref)
                    if cell in self._retired_cells(book):
                        continue                       # an input that moved: dropped when the values are loaded
                    d = book.inputs.get(cell)
                    label = d.label if d else ""
                except (KeyError, ValueError):
                    pass
            out.append({"book": bid, "ref": ref, "value": val, "label": label})
        return {"inputs": out}

    # ================================================================== scenarios
    def scenarios(self, user: str) -> List[Dict[str, Any]]:
        return self.store.scenarios(self.require_user(user))

    def save_scenario(self, user: str, name: str) -> Dict[str, Any]:
        user = self.require_user(user)
        try:
            return self.store.save_scenario(user, name, self.store.user_inputs(user))
        except ValueError as exc:
            raise ServiceError(str(exc))

    def load_scenario(self, user: str, name: str) -> Dict[str, Any]:
        user = self.require_user(user)
        values = self.store.load_scenario(user, name)
        if values is None:
            raise ServiceError("senaryo bulunamadı: %s" % name, 404)
        self.store.replace_user_inputs(user, values)
        self.et.call(self._reload_user, user)
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
        """The columns this user hid, table by table: ``{"tables": {"v/dibs/B5": ["B", "K"], ...}}``."""
        return {"tables": self.store.get("cols." + self.require_user(user)) or {}}

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

    def _tenor_date(self, text: str, pair: str = "USDTRY") -> Optional[float]:
        """The value date of a tenor ("2W", "3M", "1Y") from the pair's spot date: n weeks, or n months and then the
        next business day of the desk's calendar (Motor!A361:A523) - as the Forward sheet dates its tenors."""
        m = re.match(r"^\s*(\d{1,3})\s*([WMYwmy])\s*$", str(text or ""))
        book = self.books.get("tto")
        if m is None or book is None:
            return None
        calc = book.engine.shared

        def value(ref: str) -> Any:
            si, rc = book.cell(ref)
            return calc.get(si, *divmod(rc, COLS))

        spot = value("Forward!K2" if str(pair).upper().startswith("EUR") else "Forward!I2")
        if isinstance(spot, str):
            spot = parse_date(spot)
        if type(spot) is not float:
            return None
        holidays = set()
        if "Motor" in book.model.sheet_index:
            for si, rc in book.cells_of("Motor!A361:A523"):
                h = calc.get(si, *divmod(rc, COLS))
                if type(h) is float:
                    holidays.add(int(h))
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
                                 p.get("spot") if type(p.get("spot")) is float else None)
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
        res = self.et.call(self._add_forward, user, payload, lang)
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
        res = self.et.call(self._add_ois, user, payload, lang)
        self.bump()
        return res

    def _add_ois(self, user, payload, lang=None) -> Dict[str, Any]:
        book = self._book("tto")
        try:
            q = bl.ois_legs(self._ois_curve(user, book), self._ois_payload(payload, lang))
        except bl.TradeError as exc:
            raise ServiceError(str(exc))
        package = uuid.uuid4().hex[:12] if len(q["legs"]) > 1 else None
        ids = []
        for lg in q["legs"]:
            rec = {"dir": lg["dir"], "tenor": lg["tenor"], "rate": lg["rate"], "dv01": lg["dv01"],
                   "nominal": lg["nominal"], "cpt": lg["cpt"], "role": lg["role"], "strategy": q["strategy"],
                   "label": q["label"], "level": q["level"], "side": q["side"],
                   "cost_bp": q["info"].get("cost_bp"), "cost_usd": q["info"].get("cost_usd"),
                   "market": q["info"].get("market"), "note": str(payload.get("note") or "").strip()[:200]}
            if lg.get("mpc"):
                rec["mpc"] = lg["mpc"]
            ids.append(self.store.add_trade(self.today_iso(), "ois", rec, user, package))
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
        self.et.call(self._sync_blotter)
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
        """The TRY government bonds of the desk's Bloomberg list, each with the lists it is already in."""
        from . import bonds as bd
        lists = {name: self._list_values(user, *where) for name, where in self.BOND_LISTS.items() if where[0] in self.books}
        rows = []
        for b in bd.catalog():
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

    def list_add(self, user: str, book_id: str, ref: str, values: List[Any]) -> Dict[str, Any]:
        """Bonds added to a list of a page by ISIN: below its last bond (then into the empty rows between, when the
        end is full), for everyone when the list is a shared one, each ISIN once.  An ISIN whose check digit is
        wrong is refused; one already listed is skipped."""
        from . import bonds as bd
        user = self.require_user(user)
        book = self._book(book_id)
        try:
            cells = book.cells_of(ref)
        except (KeyError, ValueError):
            raise ServiceError("liste bulunamadı: %s" % ref, 404)
        if not all(c in book.inputs for c in cells):
            raise ServiceError("bu hücreler bir liste değil: %s" % ref)
        current = self._list_values(user, book_id, ref)
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
        self.et.call(self._clear_rows_for_everyone, book, ["%s!%s%d" % (sheet, c, r) for r in rows for c in personal])
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

    def _flag_cell(self, isin: str, listed: bool) -> Dict[str, Any]:
        return {"t": "★" if listed else "☆", "k": "s", "cls": "act flag" + (" on" if listed else ""),
                "tip": ("Trading listesinden çıkar: " if listed else "Trading listesine ekle (DİBS RV, DİBS Trading): ") + isin}

    def _universe_columns(self, book, user: Optional[str], data: Dict[str, Any], loc) -> None:
        """Tüm Kâğıtlar, completed: ☆ / ★ (onto / off the trading list), today's Broker Chat board and ▸ (the card)."""
        rows, rnums, cols = data.get("rows") or [], data.get("r") or [], list(data.get("c") or [])
        if not rows or ex.UNI_SHEET not in book.model.sheet_index:
            return
        si = book.model.sheet_index[ex.UNI_SHEET]
        calc = self._calc(user, book)
        said = self._board_bonds(user)
        flag_at = cols.index("H") if "H" in cols else None
        for i, r in enumerate(rnums):
            if r == 4:
                rows[i].extend([{"t": t, "k": "s", "b": 1, "f": "hd", "tip": tip} for t, tip in self._BOARD_HEADS]
                               + [{"t": "Kart", "k": "s", "b": 1, "f": "hd", "tip": "Kâğıdın bütün bilgisi tek pencerede"}])
                continue
            v = calc.get(si, r, 1) if r >= 5 else None
            code = "".join(str(v).split()).upper() if isinstance(v, str) else ""
            bond = code if r >= ex.UNI_OWN[0] and code and " " not in str(v).strip() and len(code) == 12 else ""
            if not bond:
                rows[i].extend([{"t": "", "k": ""} for _ in range(len(self._BOARD_HEADS) + 1)])
                continue
            if flag_at is not None and flag_at < len(rows[i]):
                rows[i][flag_at] = self._flag_cell(bond, calc.get(si, r, 8) == "★")
            rows[i].extend(self._bond_cells(said.get(bond), loc)
                           + [{"t": "▸", "k": "s", "cls": "act cardlink", "tip": "Kâğıt kartı: " + bond}])
        self._universe_quote_marks(book, calc, si, rows, rnums, cols, loc)
        data["c"] = cols + [h for h, _ in self._BOARD_HEADS] + ["Kart"]
        data["added"] = int(data.get("added") or 0) + len(self._BOARD_HEADS) + 1

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
            if r < ex.UNI_OWN[0] or not v("U"):
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

    #: the order of the kinds in the trading summary: DİBS RV's types (B / S / T / E)
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

    _TYPE_GROUPS = (("B", "Bono · kuponsuz"), ("S", "Sabit kuponlu"), ("T", "TLREF'e endeksli"), ("E", "TÜFE'ye endeksli"))

    def _trading_table(self, user: Optional[str], loc) -> Dict[str, Any]:
        """The trading list at a glance (generated): the bonds of DİBS RV kind by kind, by maturity - the price on
        the value date the bond is priced on (bid, ask, the last trade and when), what DİBS RV makes of it (yield,
        ASW, cheap / rich, signal, duration, DV01, carry), the repo T0 -> T1 implies and today's chat board."""
        book = self.books.get("tto")
        heads = ["★", "Kâğıt", "ISIN", "Vade", "Kalan yıl", "Valör", "Bid", "Ask", "Son işlem", "Ne zaman", "Getiri %",
                 "ASW / DM", "Pahalı / ucuz", "Sinyal", "Mod. süre", "DV01 / 1mn", "C+R (bp)", "T0→T1 repo %"] + \
                [h for h, _ in self._BOARD_HEADS] + ["Kart"]
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
            kind = {"bill": "B", "zero": "B", "fixed": "S", "float": "T", "cpi": "E"}.get((known or {}).get("kind")) \
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
                [cell("AG", r), cell("AI", r), cell("AO", r), self._repo_cell(cell, live, r)]
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

    def watch_view(self, user: str, locale: Optional[str] = None, days: Any = 60) -> Dict[str, Any]:
        """The user's watch list (with each item's z-score over ``days`` closes) and alarms, what fired today,
        the desk's notes."""
        user = self.require_user(user)
        loc = numfmt.get_locale(locale or self.settings.locale)
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 60
        out = self.et.call(self.watch.snapshot, user, loc, days)
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

    def alarm_add(self, user: str, book_id: str = "tto", ref: str = "", op: str = "", level: Any = None, label: str = "",
                  note: str = "", subject: Any = None, mode: str = "level", minutes: Any = None, days: Any = None) -> Dict[str, Any]:
        """An alarm on anything that can be watched: on its level (typed as the subject is shown: 35,80 on a rate
        in per cent, 250 on a spread in bp), on a move (from the day's open, from now, from the watch list's
        reference, within the last minutes; bp for rates and spreads) or on its z-score."""
        user = self.require_user(user)
        s = self._subject(subject, book_id, ref)
        if s["kind"] == "cell":
            self._book(s.get("book") or "tto")
        try:
            lvl = float(str(level).strip().replace(" ", "").replace("−", "-").replace(",", ".")) if not isinstance(level, (int, float)) else float(level)
        except (TypeError, ValueError):
            raise ServiceError("seviye bir sayı olmalı")
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

    def alarms_fired(self, user: str, since: int = 0) -> Dict[str, Any]:
        """The user's alarms that fired today after ``since`` (the last one the page has shown)."""
        user = self.require_user(user)
        mine = [e for e in self.watch.fired() if e.get("user") == user]
        last = max([int(e.get("seq") or 0) for e in self.watch.fired()] or [0])
        return {"fired": [e for e in mine if int(e.get("seq") or 0) > int(since or 0)], "last": last}

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
    def _bond_cells(q: Optional[Dict[str, Any]], loc) -> List[Dict[str, Any]]:
        """Bid, ask, last trade (or a level said without a side, soft) and the time of the last word of a bond on
        the board - four cells, empty for a bond nobody spoke of."""
        if q is None:
            return [{"t": "", "k": ""} for _ in range(4)]
        unit = q.get("unit") or "px"

        def lvl(v: Any, extra: str = "", cls: str = "") -> Dict[str, Any]:
            if type(v) is not float:
                return {"t": "", "k": ""}
            cell = {"t": numfmt.format_value(v, "0.000" if unit == "px" else "0.00", loc) + extra, "v": v, "k": "n"}
            if cls:
                cell["cls"] = cls
            return cell

        last = lvl(q.get("last"), " · biz" if q.get("last_by") == "biz" else "",
                   "buy" if q.get("last_side") == "ask" else ("sell" if q.get("last_side") == "bid" else ""))
        if type(q.get("last")) is not float and type(q.get("level")) is float:
            last = dict(lvl(q["level"], "", "soft"), tip="Seviye (işlem değil): " + (q.get("said") or ""))
        times = [x for x in (q.get("bid_time"), q.get("ask_time"), q.get("last_time"), q.get("level_time")) if x]
        return [lvl(q.get("bid")), lvl(q.get("ask")), last,
                {"t": max(times)[-8:-3] if times else "", "k": "s", "tip": max(times) if times else ""}]

    _BOARD_HEADS = [("Broker bid", "Broker Chat tahtasında bugün duran bid (bono / kuponsuzda getiri)"),
                    ("Broker ask", "Broker Chat tahtasında bugün duran offer"),
                    ("Son işlem", "Bugün chat'te geçen son işlem (biz: bizim masanın); işlem yoksa tarafı söylenmemiş son seviye "
                                  "(ihale fiyatı gibi), soluk"),
                    ("Saat", "Kâğıt için chat'te söylenen son şeyin saati")]

    def _dibs_broker_columns(self, book, user: Optional[str], data: Dict[str, Any], loc) -> None:
        """The day's broker chat next to the DİBS RV table: per bond the bid, the ask and the last trade where the
        Broker Chat board has them (resets applied), the time of the last word, the yield the broker mid stands
        for and how far it is from the screen's yield (bp; + : the brokers see it cheaper than the screen)."""
        sheet = "DİBS RV"
        rows, rnums = data.get("rows") or [], data.get("r") or []
        if not rows or sheet not in book.model.sheet_index:
            return
        si = book.model.sheet_index[sheet]
        calc = self._calc(user, book)
        self._rv_quote_marks(book, calc, si, data, loc)
        said = self._board_bonds(user)
        mkt = self._broker_market(user) if said else None
        heads = self._BOARD_HEADS + [
            ("Broker getiri %", "Broker orta fiyatının ima ettiği getiri: ekran getirisi − (fiyat − ekran fiyatı) / (ekran fiyatı · mod. süre); "
                                "bonoda kotanın kendisi"),
            ("Broker − ekran (bp)", "Broker orta getirisi − ekran getirisi (DİBS RV): + ise brokerlar kâğıdı ekrandan ucuz görüyor")]
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
            # the yield of the mid (of one side when only one stands; of the last trade when no side stands)
            imp = q.get("implied") or {}
            if unit == "yld":
                sides = [q[k] for k in ("bid", "ask") if type(q.get(k)) is float] or \
                    [q[k] for k in ("last", "level") if type(q.get(k)) is float][:1]
                screen = (self._bond_screen(mkt, q["isin"]) or {}).get("yield")
            else:
                sides = [imp[k] for k in ("bid", "ask") if type(imp.get(k)) is float] or \
                    [imp[k] for k in ("last", "level") if type(imp.get(k)) is float][:1]
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
            cells = self._bond_cells(board, loc)
            out["board"] = {"bid": cells[0]["t"], "ask": cells[1]["t"], "last": cells[2]["t"], "time": cells[3]["t"],
                            "implied": {k: v for k, v in (board.get("implied") or {}).items() if k in ("bid", "ask", "last", "screen_yield")}}
        today = self.today_iso()
        lines = [q for q in self.store.broker_quotes(today, today) if q.get("ok") and q.get("isin") == code]
        people = self._people()
        out["chat"] = []
        for q in lines:
            source, party = self._who(people, q, q.get("source") or "", q.get("party") or "")
            out["chat"].append({"time": q.get("time"), "who": ("Biz" if party == "biz" else (source or "Broker"))
                                + (" · " + q["sender"] if q.get("sender") else ""), "raw": q.get("raw") or "",
                                "event": q.get("event"), "side": q.get("side"), "bid": q.get("bid"), "ask": q.get("ask"),
                                "price": q.get("price"), "unit": q.get("unit")})
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
            if b is None or b.get("kind") not in ("float", "cpi", "bill", "zero"):
                continue
            sc = self._bond_screen(mkt, isin) or {}
            unit = "yld" if bd.quoted_in_yield(b) else "px"
            lv = self._bond_level(isin, unit, sc.get("yield") if unit == "yld" else sc.get("clean"))
            if lv is not None:
                out.append(lv)
        return out

    def _bond_pick(self, mkt, rows: List[Dict[str, Any]]) -> None:
        """A month that has several bonds of the kind ("Jan30 tlref": 02.01.30 and 09.01.30; "10/02/2027": a bill
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
        bond, its screen price (or yield, for a bill) in the DİBS RV table."""
        if mkt is not None and q.get("product") == "DIBS" and q.get("kind") == "switch":
            sw = Service._switch_screen(mkt, q)
            return sw["screen"] if sw else None
        if mkt is not None and q.get("product") == "DIBS":
            sc = Service._bond_screen(mkt, q.get("isin") or str(q.get("key") or "").replace("DIBS:", "")) or {}
            return sc.get("yield") if q.get("unit") == "yld" else sc.get("clean")
        if mkt is None or q.get("product") != "OIS":
            return None
        return bc.model_level(q, lambda t: mkt.par(t) if t in bl.OIS_TENORS else None, mkt.fra_months)

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
        items = [(q, ("bid", "ask", "price")) for q in rows] + [(r, ("bid", "ask", "last", "level")) for r in board or ()]
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

        rows = bc.parse_chat(str(text or "")[:200000], ref, _dt.date.today(), standing, nearby)
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
        self.bump()
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
        self.bump()
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

    def broker(self, user: Optional[str], date: Optional[str] = None, date_to: Optional[str] = None) -> Dict[str, Any]:
        """The chat of a day (or of every day between two dates) in the order it was said, and where every
        instrument stands after it, next to the dashboard's own curve."""
        return self.et.call(self._broker, user, date, date_to)

    def _broker(self, user, date, date_to) -> Dict[str, Any]:
        today = self.today_iso()
        day = self._broker_day(date)
        last = self._broker_day(date_to) if date_to else day
        if last < day:
            day, last = last, day
        rows, table, resets = self._broker_board(user, day, last)
        self._fx_implied(user, rows, table)
        return {"date": day, "to": last, "ranged": day != last, "today": today, "is_today": day == today == last,
                "rows": rows, "board": table, "dates": self.store.broker_dates(), "resets": resets, "gen": self.gen}

    def _broker_board(self, user, day: str, last: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """The kept lines of the days, each with whose it is, and the board they make (resets applied), each
        instrument next to where the dashboard has it."""
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

        table = bc.board([q for q in rows if not cleared(q)] if resets else rows, lambda q: q.get("party") == "biz")
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
        self.bump()
        return self.broker(user, day)

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
            self.bump()
        return {"deleted": n}

    def broker_delete(self, user: str, quote_id: int) -> Dict[str, Any]:
        self.require_user(user)
        if not self.store.delete_broker_quote(int(quote_id)):
            raise ServiceError("kayıt bulunamadı", 404)
        self.bump()
        return {"deleted": int(quote_id)}

    def broker_export(self, user: Optional[str], date: Optional[str] = None, date_to: Optional[str] = None) -> Tuple[bytes, str]:
        """The chat of a day or a period as an .xlsx file: the board, then every line."""
        return self.et.call(self._broker_export, user, date, date_to)

    def _broker_export(self, user, date, date_to) -> Tuple[bytes, str]:
        from .xlsx import XlsxBook
        data = self._broker(user, date, date_to)
        names = {u["name"]: u["display"] for u in self.store.users()}
        kinds = {"outright": "Outright", "spread": "Spread", "fly": "Fly", "fra": "FRA", "fwd": "Forward"}
        events = {"quote": "Kota", "trade": "İşlem", "ref": "Geri çekildi", "interest": "İlgi", "level": "Seviye", "note": "Not",
                  "text": "Metin"}
        wb = XlsxBook()
        ws = wb.add_sheet("Tahta")
        ws.row(1, 1, ["Ürün", "Tür", "Enstrüman", "Birim", "Bid", "Bid saati", "Ask", "Ask saati", "Son işlem", "İşlem saati",
                      "Model mid", "Bid − mid (bp)", "Ask − mid (bp)", "Bizim bid", "Bizim ask", "İşlemi yapan"], bold=True, fill="E7E6E6")
        for i, r in enumerate(data["board"]):
            fmt = "#,##0.00" if r["unit"] == "pct" else "#,##0.0"
            line = [r["product"], kinds.get(r["kind"], r["kind"]), r["label"], "%" if r["unit"] == "pct" else "bp", r["bid"], r["bid_time"],
                    r["ask"], r["ask_time"], r["last"], r["last_time"], r["mid"], r["bid_diff"], r["ask_diff"], r.get("our_bid"),
                    r.get("our_ask"), {"biz": "Biz", "broker": "Broker"}.get(r.get("last_by") or "", "")]
            for k, v in enumerate(line):
                ws.set(2 + i, 1 + k, v, fmt=fmt if k in (4, 6, 8, 10, 13, 14) else ("#,##0.0" if k in (11, 12) else None))
        ws.autosize()
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
        self.et.call(self._sync_blotter)
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
