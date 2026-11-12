"""Application service: everything the web layer needs, independent of HTTP.

One dedicated engine thread (large stack, serialises all calculation work) owns the workbook engines.
The service keeps per-user input overlays, the shared desk inputs (RET curve, calendars, blotter) and a
generation counter that increases whenever something visible may have changed.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import os
import queue
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import blotter as bl
from .books import Book, formula_text, load_books, snapshot_today
from .config import Settings
from .inputs import InputError, parse_amount, parse_clipboard, parse_date, parse_input, parse_number
from .marketdata import ReplayProvider
from .marketdata.replay import snapshot_from_model
from .render import Renderer
from .store import Store, user_key
from .views import load_views
from .xl import numfmt
from .xl.engine import Calc, Clock
from .xl.errors import XlError
from .xl.model import COLS, a1, parse_a1, parse_range
from .xl.values import date_to_serial, serial_to_date

RET_TENORS = ["ON", "TN", "1W", "2W", "3W", "1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y", "18M", "2Y"]
RET_FIRST_ROW = 33


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        Exception.__init__(self, message)
        self.status = status


class EngineThread(object):
    """Runs every calculation on one thread with a large stack (formula chains recurse deeply)."""

    def __init__(self):
        self._q: "queue.Queue" = queue.Queue()
        old = threading.stack_size()
        try:
            threading.stack_size(256 * 1024 * 1024)
        except (ValueError, RuntimeError):
            pass
        self._t = threading.Thread(target=self._loop, name="tto-engine", daemon=True)
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

    # ================================================================== setup
    def _setup(self, provider) -> None:
        s = self.settings
        self.mode = "replay"
        self.mode_note = ""
        if provider is None and s.mode in ("auto", "live"):
            try:
                from .marketdata.bloomberg import BloombergProvider
                provider = BloombergProvider(s.bbg_host, s.bbg_port, stream=s.bbg_stream, price_poll=s.bbg_price_poll,
                                             max_hits_per_day=s.bbg_max_hits, bfx=s.bbg_bfx)
                provider.start()
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
                demo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "replay_usd.json")
                if os.path.exists(demo):
                    provider.load_quotes(demo)
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

    # ================================================================== lifecycle / events
    def start(self) -> None:
        if self._market_thread is None:
            self._market_thread = threading.Thread(target=self._market_loop, name="tto-market", daemon=True)
            self._market_thread.start()
            if self.mode == "live":
                threading.Thread(target=self._warmup_safe, name="tto-warmup", daemon=True).start()

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
        try:
            stop = getattr(self.provider, "stop", None)
            if stop:
                stop()
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
        return {"mode": self.mode, "note": self.mode_note, "provider": prov, "gen": self.gen, "today": today,
                "books": {bid: {"title": b.title, "formulas": b.model.formula_count(),
                                "source": b.model.meta.get("source")} for bid, b in self.books.items()},
                "port": self.settings.port}

    def nav(self) -> List[Dict[str, Any]]:
        pages = [{"id": v["id"], "title": v["title"], "group": v.get("group", ""), "book": v["book"],
                  "sheet": v.get("sheet")} for v in self.views]
        if "tto" in self.books:
            pages.append({"id": "blotter", "title": "Günlük İşlemler", "group": "Masa", "book": "tto",
                          "sheet": bl.SHEET, "custom": True})
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
            sheet = p.get("sheet", sheet_default)
            try:
                if p["type"] in ("table", "notes"):
                    entry["range"] = p["range"]
                    entry["data"] = R.table(calc, sheet, p["range"], loc, overlay)
                    if p.get("lift", True):
                        own = _lift_title(entry["data"])
                        if own and not p.get("keep_title"):
                            entry["title"] = own
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
        return {"id": v["id"], "title": v["title"], "book": book.id, "sheet": sheet_default, "gen": gen,
                "panels": panels, "ms": int((time.time() - t0) * 1000), "note": v.get("note")}

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
                    items.append({"label": lab, "text": cell.get("t", ""), "v": cell.get("v")})
        return {"items": items, "gen": self.gen}

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
                   lang: Optional[str] = None) -> Dict[str, Any]:
        """items: [{"ref": "Forward!D2", "value": "03.12.2026"} ...] (value None / "" clears).

        ``lang`` is the number format the texts were typed / copied in ("tr": 1.234,56 – "en": 1,234.56).
        """
        user = self.require_user(user)
        res = self.et.call(self._set_inputs, user, book_id, items, allow_adhoc, lang or self.settings.locale)
        self.bump()
        res["gen"] = self.gen
        return res

    def _set_inputs(self, user, book_id, items, allow_adhoc, lang="tr") -> Dict[str, Any]:
        book = self._book(book_id)
        if len(items) > 20000:
            raise ServiceError("çok fazla hücre")
        user_vals: Dict[Tuple[int, int], Any] = {}
        user_clear: List[Tuple[int, int]] = []
        shared_vals: Dict[Tuple[int, int], Any] = {}
        errors: List[str] = []
        for it in items:
            ref = it.get("ref")
            try:
                si, rc = book.cell(ref)
            except (KeyError, ValueError, AttributeError):
                errors.append("%s: hücre bulunamadı" % ref)
                continue
            d = book.inputs.get((si, rc))
            if d is None:
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
            elif val is None and rc in sheet.fml:
                user_clear.append((si, rc))          # blanking a formula default = back to the formula
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
        return {"applied": len(shared_vals) + len(user_vals) + len(user_clear), "errors": errors}

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

    def blotter(self, user: Optional[str], date: Optional[str] = None, locale: Optional[str] = None) -> Dict[str, Any]:
        return self.et.call(self._blotter, user, date, locale)

    def _blotter(self, user, date, locale) -> Dict[str, Any]:
        book = self._book("tto")
        today = self.today_iso()
        date = date or today
        try:
            _dt.date.fromisoformat(date)
        except ValueError:
            raise ServiceError("tarih anlaşılamadı: %s" % date)
        trades = self.store.trades(date)
        out: Dict[str, Any] = {"date": date, "today": today, "is_today": date == today, "trades": trades,
                               "cost": bl.summarise(trades), "dates": self.store.trade_dates(), "gen": self.gen,
                               "tenors": bl.OIS_TENORS}
        loc = numfmt.get_locale(locale or self.settings.locale)
        if date == today:
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
            self.store.save_blotter_snapshot(date, {"sheet": sheet_panels})
        else:
            snap = self.store.blotter_snapshot(date)
            out["sheet"] = snap.get("sheet") if snap else []
            out["snapshot_at"] = snap.get("snapshot_at") if snap else None
        return out

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
            n = parse_number(man, lang, prefer_decimal=True)
            if n is not None and basis == "TRY" and not (man.strip().endswith("%") or man.strip().startswith("%")) and abs(n) >= 1.0:
                n /= 100.0
            p["manual"] = n
        elif isinstance(man, (int, float)):
            p["manual"] = float(man)
        return p

    def _quote_forward(self, user, payload, lang=None) -> Dict[str, Any]:
        book = self._book("tto")
        p = self._fwd_payload(payload, lang)
        if type(p.get("value_date")) is not float:
            raise ServiceError("valör tarihi gerekli")
        ov = self._overlay(user_key(user), book) if user else {}
        try:
            q = bl.price_forward(book, ov, p["value_date"], str(p.get("basis", "RET_MID")).upper(),
                                 p.get("manual") if type(p.get("manual")) is float else None)
        except bl.TradeError as exc:
            raise ServiceError(str(exc))
        amount = p.get("amount")
        if type(amount) is float and amount > 0:
            q["amount"] = amount
            q["tl"] = amount * q["forward"]
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
        for k in ("level", "dv01", "nominal", "short_rate", "wing1_rate", "wing2_rate", "start_rate",
                  "start_months", "end_months"):
            v = p.get(k)
            if isinstance(v, str):
                rate_like = k in ("short_rate", "wing1_rate", "wing2_rate", "start_rate") or \
                    (k == "level" and strategy in ("outright", "fra"))
                n = parse_amount(v, lang) if k in ("dv01", "nominal") else parse_number(v, lang, prefer_decimal=True)
                if n is not None and rate_like and not ("%" in v) and abs(n) >= 1.0:
                    n /= 100.0                    # 35,5 typed for 35,5 %
                p[k] = n
            elif isinstance(v, bool):
                p[k] = None
            elif isinstance(v, (int, float)):
                x = float(v)
                if k == "level" and strategy in ("outright", "fra") and abs(x) >= 1.0:
                    x /= 100.0
                p[k] = x
        return p

    def quote_ois(self, user: Optional[str], payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        return self.et.call(self._quote_ois, user, payload, lang)

    def _quote_ois(self, user, payload, lang=None) -> Dict[str, Any]:
        book = self._book("tto")
        calc = self._calc(user_key(user) if user else None, book)
        try:
            return bl.ois_legs(bl.OisMarket(book, calc), self._ois_payload(payload, lang))
        except bl.TradeError as exc:
            raise ServiceError(str(exc))

    def ois_market(self, user: Optional[str]) -> Dict[str, Any]:
        """Mid par rates / annuities per tenor for the trade form."""
        return self.et.call(self._ois_market, user)

    def _ois_market(self, user) -> Dict[str, Any]:
        book = self._book("tto")
        mkt = bl.OisMarket(book, self._calc(user_key(user) if user else None, book))
        rows = []
        for t in bl.OIS_TENORS:
            try:
                rows.append({"tenor": t, "par": mkt.par(t), "annuity": mkt.annuity(t)})
            except bl.TradeError:
                rows.append({"tenor": t, "par": mkt.par(t), "annuity": None})
        out = {"tenors": rows, "gen": self.gen}
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
            q = bl.ois_legs(bl.OisMarket(book, self._calc(user, book)), self._ois_payload(payload, lang))
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
            ids.append(self.store.add_trade(self.today_iso(), "ois", rec, user, package))
        self._sync_blotter()
        q["ids"] = ids
        return q

    def add_bond(self, user: str, payload: Dict[str, Any], lang: Optional[str] = None) -> Dict[str, Any]:
        user = self.require_user(user)
        lang = lang or self.settings.locale
        inst = str(payload.get("instrument") or "").strip()[:60]
        if not inst:
            raise ServiceError("enstrüman gerekli")
        amount = payload.get("amount")
        amount = parse_amount(amount, lang) if isinstance(amount, str) else (float(amount) if isinstance(amount, (int, float)) else None)
        price = payload.get("price")
        price = parse_number(price, lang, prefer_decimal=True) if isinstance(price, str) else (float(price) if isinstance(price, (int, float)) else None)
        if amount is None or amount == 0:
            raise ServiceError("tutar gerekli (+ alış / − satış)")
        if price is None or price <= 0:
            raise ServiceError("fiyat gerekli")
        side = str(payload.get("dir") or "").upper()
        if side == "S":
            amount = -abs(amount)
        elif side == "B":
            amount = abs(amount)
        rec = {"instrument": inst, "amount": amount, "price": price, "note": str(payload.get("note") or "").strip()[:200]}
        tid = self.store.add_trade(self.today_iso(), "bond", rec, user)
        self.et.call(self._sync_blotter)
        self.bump()
        rec["id"] = tid
        return rec

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
