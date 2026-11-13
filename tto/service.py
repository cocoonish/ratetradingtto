"""Application service: everything the web layer needs, independent of HTTP.

One dedicated engine thread (large stack, serialises all calculation work) owns the workbook engines.
The service keeps per-user input overlays, the shared desk inputs (RET curve, calendars, blotter) and a
generation counter that increases whenever something visible may have changed.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import json
import os
import queue
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote as _quote

from . import blotter as bl
from . import brokerchat as bc
from . import volcarry as vc
from .books import Book, formula_text, load_books, snapshot_today
from .config import Settings
from .inputs import InputError, parse_amount, parse_clipboard, parse_date, parse_input, parse_number
from .marketdata import ReplayProvider
from .marketdata.replay import snapshot_from_model
from .render import Renderer
from .store import Store, user_key
from .views import layout as view_layout, load_views
from .xl import numfmt
from .xl.engine import Calc, Clock
from .xl.errors import XlError
from .xl.model import COLS, a1, parse_a1, parse_range
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
        self._listeners: List[Callable[[int], None]] = []
        self._overlays: Dict[Tuple[str, str], Dict[Tuple[int, int], Any]] = {}
        self._view_cache: Dict[Tuple, Dict[str, Any]] = {}
        self._stop = threading.Event()
        self._market_thread: Optional[threading.Thread] = None
        self.started_at = time.time()
        self.et.call(self._setup, provider)
        from .history import History
        self.history = History(self)

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
                                 options=inp.get("options"), view=v["id"])
                except (KeyError, ValueError):
                    continue
        tto = self.books.get("tto")
        if tto is not None:
            for ref in bl.input_ranges():
                tto.declare(ref, scope="shared", group="blotter", view="blotter")
            for ref in ("Forward!D2", "Forward!B163", "Forward!L163"):
                tto.declare(ref, scope="user", group="fwd-pricer", view="forward")
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
        try:
            stop = getattr(self.provider, "stop", None)
            if stop:
                stop()
        finally:
            try:
                self.history.stop()
            finally:
                self.et.stop()

    def _market_loop(self) -> None:
        last_day = None
        busy = getattr(self.provider, "busy", None)
        while not self._stop.wait(0.3 if (busy is not None and busy()) else self.settings.tick_seconds):
            try:
                drain = getattr(self.provider, "drain_changes", None)
                keys = drain() if drain else []
                day = _dt.date.today()
                day_changed = last_day is not None and day != last_day
                last_day = day
                if keys or day_changed or self.mode == "live":
                    changed = self.et.call(self._apply_market, keys)
                    if changed or day_changed:
                        if day_changed:
                            self.et.call(self._sync_blotter)
                        self.bump()
            except Exception:  # noqa: BLE001 - the loop must survive anything
                continue

    def _apply_market(self, keys) -> bool:
        changed = False
        for b in self.books.values():
            if keys and b.engine.market_changed(keys):
                changed = True
            before = b.engine.shared.evals
            b.engine.clock_tick()
        return changed or bool(keys)

    def bump(self) -> int:
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
        try:
            return self.store.login(name)
        except ValueError as exc:
            raise ServiceError(str(exc))

    def require_user(self, user: Optional[str]) -> str:
        if not user:
            raise ServiceError("önce isminizle giriş yapın", 401)
        key = user_key(user)
        if not self.store.user_exists(key):
            raise ServiceError("kullanıcı bulunamadı – tekrar giriş yapın", 401)
        return key

    def _overlay(self, user: str, book: Book) -> Dict[Tuple[int, int], Any]:
        key = (user, book.id)
        ov = self._overlays.get(key)
        if ov is None:
            ov = {}
            fresh = []
            for (bid, ref), val in self.store.user_inputs(user, book.id).items():
                try:
                    cell = book.cell(ref)
                except (KeyError, ValueError):
                    continue
                if cell not in book.inputs:
                    fresh.append(ref)
                ov[cell] = _from_json(val)
            for ref in fresh:
                book.declare(ref, scope="user", group="adhoc")
            self._overlays[key] = ov
            if ov:
                book.engine.set_user_inputs(user, ov)
        return ov

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

    def nav(self) -> List[Dict[str, Any]]:
        pages = []
        for v in self.views:
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
            pages.append({"id": "blotter", "title": "Günlük İşlemler", "group": "Masa", "book": "tto",
                          "sheet": bl.SHEET, "custom": True})
            pages.append({"id": "broker", "title": "Broker Chat", "group": "Masa", "book": "tto", "sheet": None, "custom": True})
            # pages of the dashboard's own: what happened over time, and the settings behind it
            pages.append({"id": "eod", "title": "Gün Sonu Matrisi", "group": "Masa", "book": "tto", "sheet": None, "custom": True})
            pages.append({"id": "mpc", "title": "PPK Fiyatlama Geçmişi", "group": "TRY Faiz", "book": "tto", "sheet": None,
                          "custom": True})
            pages.append({"id": "vol", "title": "Realized Vol · Carry", "group": "TRY Faiz", "book": "tto", "sheet": None,
                          "custom": True})
            pages.append({"id": "settings", "title": "Ayarlar · Toplantı takvimi", "group": "Araçlar", "book": "tto",
                          "sheet": None, "custom": True})
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
        book = self.books[v["book"]]
        loc = numfmt.get_locale(locale or self.settings.locale)
        calc = self._calc(user, book)
        overlay = self._overlay(user, book) if user else None
        R = self.renderers[book.id]
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
                        # a long helper table: its first rows here, all of it in the sheet explorer
                        r1, c1, r2, c2 = parse_range(rng)
                        if r2 - r1 + 1 > int(p["max_rows"]):
                            rng = "%s:%s" % (a1(r1 * COLS + c1), a1((r1 + int(p["max_rows"]) - 1) * COLS + c2))
                            entry["note"] = ("İlk %d satır gösteriliyor (toplam %d). Tamamı: Sayfa gezgini → %s!%s"
                                             % (int(p["max_rows"]), r2 - r1 + 1, sheet, p["range"]))
                    # columns hidden in Excel stay out of the way until the helper tables are asked for
                    entry["data"] = R.table(calc, sheet, rng, loc, overlay, show_hidden=show_hidden)
                    if p.get("lift", True):
                        own = _lift_title(entry["data"])
                        if own and not p.get("keep_title"):
                            entry["title"] = own
                    if p.get("header"):
                        _column_captions(entry["data"], p["header"])
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
        links = self._shortcuts(v)
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
        errors: List[str] = []
        skipped = 0
        for it in items:
            ref = it.get("ref")
            try:
                si, rc = book.cell(ref)
            except (KeyError, ValueError, AttributeError):
                errors.append("%s: hücre bulunamadı" % ref)
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
                                  d.kind, book.options_for(si, rc), lang)
            except InputError as exc:
                errors.append("%s: %s" % (ref, exc))
                continue
            if d.scope == "shared":
                shared_vals[(si, rc)] = val
            elif val is None and (rc in sheet.fml or d.group == "adhoc"):
                # blanking a formula default = back to the formula; blanking a value typed over any other cell
                # ("elle değer") = back to what the workbook holds there
                user_clear.append((si, rc))
            else:
                user_vals[(si, rc)] = val
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
        res: Dict[str, Any] = {"applied": len(shared_vals) + len(user_vals) + len(user_clear), "errors": errors}
        if lenient:
            res["skipped"] = skipped
        return res

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
                    d = book.inputs.get(book.cell(ref))
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
            for pid, title, rng in (("fwd", "USDTRY Forward · vade kovaları", "P1:W20"), ("ois", "OIS · vade özeti", "O22:W39"),
                                    ("bond", "Bonds", "P41:V84"), ("cpt", "OIS — CPT x VADE (DV01 USD)", "P87:V349")):
                try:
                    data = R.table(calc, bl.SHEET, rng, loc, None)
                    _lift_title(data)
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
                    for i, row in enumerate(t.get("rows") or []):
                        for j, cell in enumerate(row):
                            if cell.get("sk"):
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

    def quote_forward(self, user: Optional[str], payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        return self.et.call(self._quote_forward, user, payload, lang)

    def _fwd_payload(self, payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        lang = lang or self.settings.locale
        p = dict(payload)
        vd = p.get("value_date")
        if isinstance(vd, str):
            d = parse_date(vd)
            if d is None:
                raise ServiceError("valör tarihi anlaşılamadı: %r" % vd)
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
                "source": snap["src"], "live": self.mode == "live",
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

    def carry_vol(self, user: Optional[str], kind: str = "fly", window: Any = 60) -> Dict[str, Any]:
        """The flies (or spreads) of the Carry & Roll sheet with their realized volatility: carry + roll over
        the sheet's two horizons against the volatility over the same time."""
        kind = "spread" if str(kind or "").lower().startswith("s") else "fly"
        try:
            window = int(window)
        except (TypeError, ValueError):
            window = 60
        if window not in vc.WINDOWS:
            window = 60
        table = self.et.call(self._carry_table, user, kind)
        curves, months, info = self._vol_curves()
        days = {name: h["days"] for name, h in table["horizons"].items()}
        rows = [vc.carry_row(vc.item_of(kind, r["tenors"]), r["market"], {"a": r["a"], "b": r["b"]}, days,
                             curves["OIS"], months["OIS"], window) for r in table["rows"]]
        return {"kind": kind, "window": window, "windows": list(vc.WINDOWS), "horizons": table["horizons"], "rows": rows,
                "history": info, "gen": self.gen}

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
        spot = book.cell("OIS_MAIN!B2")
        spot = calc.get(spot[0], *divmod(spot[1], COLS))
        horizons: Dict[str, Any] = {}
        for name, row in (("a", 3), ("b", 22)):
            text, end = cell("A%d" % row), cell("C%d" % row)
            m = re.search(r":\s*([^–-]+)", text) if isinstance(text, str) else None
            days = vc.week_days(serial_to_date(spot), serial_to_date(end)) if type(spot) is float and type(end) is float else 0
            horizons[name] = {"label": m.group(1).strip() if m else ("Ufuk " + name.upper()), "days": days,
                              "date": serial_to_date(end).isoformat() if type(end) is float else None}
        return {"rows": rows, "horizons": horizons}

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
    def _broker_model(mkt, q: Dict[str, Any]) -> Optional[float]:
        """Where the dashboard's own TRY OIS curve has an instrument of the chat (cross-currency: no answer)."""
        if mkt is None or q.get("product") != "OIS":
            return None
        return bc.model_level(q, lambda t: mkt.par(t) if t in bl.OIS_TENORS else None, mkt.fra_months)

    def _broker_rows(self, user: Optional[str], text: str, date: Optional[str]) -> List[Dict[str, Any]]:
        """A pasted chat as rows to keep.  A level without its big figure ("90 bid") is completed from what the
        chat last said about the instrument - in the same paste, then earlier that day - and then from the curve."""
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
                if r.get("ok") and r.get("key") == q["key"] and r.get("unit") == "pct":
                    for name in ("price", "ask", "bid"):
                        if r.get(name) is not None:
                            return r[name]
            return self._broker_model(mkt, q)

        def standing(q: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            return next((row for row in bc.board(before(q)) if row["key"] == q["key"]), None)

        rows = bc.parse_chat(str(text or "")[:200000], ref, _dt.date.today(), standing)
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

    def broker_parse(self, user: Optional[str], text: str, date: Optional[str] = None) -> Dict[str, Any]:
        """How a pasted chat would be read - nothing is kept.  ``dup`` marks what is stored already."""
        return self.et.call(self._broker_parse, user, text, date)

    def _broker_parse(self, user, text, date) -> Dict[str, Any]:
        rows = self._broker_rows(user, text, date)
        have: Dict[str, set] = {}
        for q in rows:
            if q["date"] not in have:
                have[q["date"]] = self.store.broker_marks(q["date"])
            q["dup"] = (q["time"], q["mark"]) in have[q["date"]]
        return {"date": self._broker_day(date), "rows": rows, "quotes": sum(1 for q in rows if q.get("ok")),
                "texts": sum(1 for q in rows if not q.get("ok")), "known": sum(1 for q in rows if q["dup"])}

    def broker_add(self, user: str, text: str, date: Optional[str] = None, source: str = "", texts: bool = True) -> Dict[str, Any]:
        """Keep a pasted chat: every line with its time, sender and reading.  Pasting a stretch again adds
        only what is new.  ``texts`` off: lines that name no instrument are left out."""
        user = self.require_user(user)
        res = self.et.call(self._broker_add, user, text, date, source, texts)
        self.bump()
        return res

    def _broker_add(self, user, text, date, source, texts) -> Dict[str, Any]:
        rows = self._broker_rows(user, text, date)
        if not texts:
            rows = [q for q in rows if q.get("ok")]
        if not rows:
            raise ServiceError("kaydedilecek satır yok")
        source = str(source or "").strip()[:40]
        for q in rows:
            q["source"] = source
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
        rows = self.store.broker_quotes(day, last)
        mkt = self._broker_market(user)
        table = bc.board(rows)
        for row in table:
            row.update(bc.against(row, self._broker_model(mkt, row)))
        return {"date": day, "to": last, "ranged": day != last, "today": today, "is_today": day == today == last,
                "rows": rows, "board": table, "dates": self.store.broker_dates(), "gen": self.gen}

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
                      "Model mid", "Bid − mid (bp)", "Ask − mid (bp)"], bold=True, fill="E7E6E6")
        for i, r in enumerate(data["board"]):
            fmt = "#,##0.00" if r["unit"] == "pct" else "#,##0.0"
            line = [r["product"], kinds.get(r["kind"], r["kind"]), r["label"], "%" if r["unit"] == "pct" else "bp", r["bid"], r["bid_time"],
                    r["ask"], r["ask_time"], r["last"], r["last_time"], r["mid"], r["bid_diff"], r["ask_diff"]]
            for k, v in enumerate(line):
                ws.set(2 + i, 1 + k, v, fmt=fmt if k in (4, 6, 8, 10) else ("#,##0.0" if k in (11, 12) else None))
        ws.autosize()
        ls = wb.add_sheet("Kayıt")
        ls.row(1, 1, ["Tarih", "Saat", "Kimden", "Kaynak", "Mesaj", "Ürün", "Tür", "Enstrüman", "Olay", "Bid", "Ask", "İşlem / seviye",
                      "Birim", "Not", "Giren"], bold=True, fill="E7E6E6")
        for i, q in enumerate(data["rows"]):
            fmt = "#,##0.00" if q.get("unit") == "pct" else "#,##0.0"
            line = [date_to_serial(_dt.date.fromisoformat(q["date"])), q["time"], q.get("sender") or "", q.get("source") or "",
                    q.get("raw") or "", q.get("product") or "", kinds.get(q.get("kind"), q.get("kind") or ""), q.get("label") or "",
                    events.get(q.get("event"), q.get("event") or ""), q.get("bid"), q.get("ask"), q.get("price"),
                    ("%" if q.get("unit") == "pct" else "bp") if q.get("ok") else "", q.get("note") or "",
                    names.get(q.get("created_by"), q.get("created_by") or "")]
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
