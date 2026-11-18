"""HTTP layer (Starlette): JSON API, server-sent events and the static single-page app."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from typing import Any, Callable, Dict, Optional

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import auth
from .config import Settings
from .service import Service, ServiceError

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

#: what answers without a session: the sign-in itself (the page and its files are outside /api/)
PUBLIC_API = ("/api/auth", "/api/login", "/api/logout", "/api/account-request", "/api/setup")

# Every file sent names its type, and on Windows Python reads the types from the registry the first time one is asked
# for: 8 430 keys on the desk machine, each read letting go of the interpreter lock - next to a calculating thread the
# first page waited 80 s for them (and the whole server with it).  Read here, before anything calculates.
if not mimetypes.inited:
    mimetypes.init()


def _finite(v: Any) -> Any:
    """``v`` with every infinity / NaN replaced by ``None`` (JSON has neither)."""
    if type(v) is float:
        return v if v - v == 0.0 else None
    if isinstance(v, dict):
        return {k: _finite(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_finite(x) for x in v]
    return v


class _Json(JSONResponse):
    """A JSON answer that survives a stray infinity / NaN: the engine turns those into ``#NUM!``, but a number worked
    out elsewhere (a ratio of two closes, a z-score) could still be one - one such number used to fail the whole page
    with a 500.  The common case costs nothing: the payload is cleaned only when it cannot be written as it is."""

    def render(self, content: Any) -> bytes:
        try:
            return super().render(content)
        except ValueError:
            return super().render(_finite(content))


class _Static(StaticFiles):
    """Static files that the browser always revalidates (so an updated dashboard is picked up at once)."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _user(request: Request) -> Optional[str]:
    """The signed-in user of the request (set by the session gate; ``None`` only on the sign-in routes)."""
    return request.scope.get("tto_user")


def _role(request: Request) -> str:
    """The signed-in user's role ("admin" / "user"), as the session gate found it."""
    return request.scope.get("tto_role") or "user"


def _since(request: Request) -> Optional[int]:
    """``?since=<generation>``: what the page has already (``None``: everything is asked for)."""
    try:
        return int(request.query_params["since"])
    except (KeyError, ValueError):
        return None


def _token(request: Request) -> Optional[str]:
    """The session token: the cookie the browser keeps, or ``Authorization: Bearer …`` (scripts, tests)."""
    head = request.headers.get("authorization") or ""
    if head[:7].lower() == "bearer ":
        return head[7:].strip() or None
    return request.cookies.get(auth.COOKIE) or None


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


#: methods that change something: a browser may send them only from the dashboard's own page
UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def _foreign(request: Request) -> bool:
    """A request a browser sent from another page than the dashboard's own - another site, or another port of this
    computer (the same "site" for a SameSite cookie, so the cookie would go along).  Scripts and tests send neither
    header and are not foreign."""
    site = (request.headers.get("sec-fetch-site") or "").lower()
    if site and site not in ("same-origin", "none"):
        return True
    origin = request.headers.get("origin")
    if origin is None:
        return False
    own = "%s://%s" % (request.url.scheme, request.headers.get("host") or "")
    return origin.rstrip("/").lower() != own.lower()


class _SessionGate(object):
    """Every request learns its user from its session; ``/api/…`` answers 401 without one (except the sign-in
    routes).  The page and its files are served to anybody - they show the sign-in screen."""

    def __init__(self, app, service: Callable[[], Optional[Service]]):
        self.app = app
        self.service = service

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        token = _token(request)
        svc = self.service()
        user = role = None
        if svc is not None and token:
            # a session looked up lately is known without a database query; another is looked up in a thread (the
            # event loop never waits on SQLite)
            hit = svc.cached_session(token)
            if hit is None:
                hit = await run_in_threadpool(svc.resolve_session, token)
            user, role = hit
            svc.saw(user, token)                       # (who has the dashboard open: their calculations are kept; presence)
        scope["tto_user"] = user
        scope["tto_role"] = role
        scope["tto_token"] = token
        path = scope.get("path") or ""
        if path.startswith("/api/") and scope.get("method") in UNSAFE_METHODS and _foreign(request):
            await JSONResponse({"error": "başka bir sayfadan gelen istek reddedildi"}, status_code=403)(scope, receive, send)
            return
        if user is None and path.startswith("/api/") and path not in PUBLIC_API:
            await JSONResponse({"error": "giriş gerekli", "login": True}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _lang(request: Request) -> Optional[str]:
    lang = request.query_params.get("lang") or request.headers.get("x-tto-lang")
    return lang if lang in ("tr", "en") else None


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ServiceError("geçersiz istek gövdesi")
    if not isinstance(data, dict):
        raise ServiceError("geçersiz istek gövdesi")
    return data


#: requests that may wait in a thread for the calculation thread at once (Starlette has 40 threads, shared with the
#: static files and the sign-in: a slow calculation must not take all of them)
ENGINE_THREADS = 12


def create_app(service: Optional[Service] = None, settings: Optional[Settings] = None) -> Starlette:
    state: Dict[str, Any] = {"service": service, "slots": None}

    def svc() -> Service:
        return state["service"]

    async def call(fn, *args, **kw):
        """``fn`` in a thread - one of at most ENGINE_THREADS: what waits for the calculation thread queues here."""
        slots = state["slots"]
        if slots is None:
            slots = state["slots"] = asyncio.Semaphore(ENGINE_THREADS)
        async with slots:
            return await run_in_threadpool(fn, *args, **kw)

    async def call_free(fn, *args, **kw):
        """``fn`` in a thread, without waiting for a place: work that never waits for the calculation thread."""
        return await run_in_threadpool(fn, *args, **kw)

    async def engine(fut):
        """The result of a calculation-thread future, awaited without holding a thread."""
        return await asyncio.wrap_future(fut)

    def ok(data: Any) -> JSONResponse:
        return _Json(data)

    def handler(fn):
        async def wrapped(request: Request):
            try:
                return await fn(request)
            except ServiceError as exc:
                return JSONResponse(dict(getattr(exc, "data", None) or {}, error=str(exc)), status_code=exc.status)
            except Exception as exc:  # noqa: BLE001 - never leak a traceback to the browser (it goes to the log)
                s = state["service"]
                if s is not None:
                    s.ops.failure("%s %s" % (request.method, request.url.path), exc)
                return JSONResponse({"error": "sunucu hatası: %s" % (str(exc)[:300] or type(exc).__name__)},
                                    status_code=500)
        return wrapped

    # ------------------------------------------------------------------ pages
    async def index(request: Request):
        return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------------ sign-in, accounts
    def signed_in(request: Request, token: str, me: Dict[str, Any]) -> JSONResponse:
        resp = _Json(me)
        resp.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, path="/", httponly=True, samesite="strict",
                        secure=request.url.scheme == "https")
        return resp

    @handler
    async def auth_state(request: Request):
        return ok(await call_free(svc().auth_state, _user(request), auth.is_local(_ip(request))))

    @handler
    async def login(request: Request):
        data = await _body(request)
        token, me = await call_free(svc().authenticate, data.get("name"), data.get("password"), _ip(request))
        return signed_in(request, token, me)

    @handler
    async def logout(request: Request):
        resp = _Json(await call_free(svc().logout, request.scope.get("tto_token")))
        resp.delete_cookie(auth.COOKIE, path="/")
        return resp

    @handler
    async def account_request(request: Request):
        data = await _body(request)
        return ok(await call_free(svc().request_account, data.get("name"), data.get("password"), data.get("note")))

    @handler
    async def setup(request: Request):
        data = await _body(request)
        token, me = await call_free(svc().setup_admin, data.get("name"), data.get("password"), auth.is_local(_ip(request)),
                               _ip(request))
        return signed_in(request, token, me)

    @handler
    async def password(request: Request):
        data = await _body(request)
        return ok(await call_free(svc().change_password, _user(request), data.get("old"), data.get("new"),
                             request.scope.get("tto_token")))

    @handler
    async def admin_users(request: Request):
        return ok(await call_free(svc().accounts, _user(request)))

    @handler
    async def admin_action(request: Request):
        data = await _body(request)
        return ok(await call_free(svc().admin_action, _user(request), request.path_params["action"], data,
                             request.scope.get("tto_token")))

    @handler
    async def admin_backup(request: Request):
        # when and where the daily backup goes (administrators only): GET reads, POST saves - or {"reset": true}
        if request.method == "GET":
            return ok(await call_free(svc().backup_settings, _user(request)))
        data = await _body(request)
        return ok(await call_free(svc().set_backup_settings, _user(request), data.get("values"), bool(data.get("reset"))))

    @handler
    async def admin_backup_now(request: Request):
        return ok(await call_free(svc().backup_run, _user(request)))

    # ------------------------------------------------------------------ session / status

    @handler
    async def users(request: Request):
        return ok({"users": await call_free(svc().store.users)})

    @handler
    async def presence(request: Request):
        # who is at the desk (presence.py): GET - the list, the same for everybody (no address); POST {"idle": seconds} -
        # the page's word that somebody typed, clicked, scrolled or moved the mouse in it (at most once a minute; memory
        # only, no thread)
        if request.method == "GET":
            return ok(await call_free(svc().presence_view, _user(request)))
        data = await _body(request)
        svc().presence.active(_user(request), request.scope.get("tto_token"), data.get("idle"))
        return ok({"ok": True})

    @handler
    async def status(request: Request):
        return ok(await call_free(svc().status_for, _user(request)))

    @handler
    async def progress(request: Request):
        # where the long calculations are (progress.py): counters read, nothing computed - the top bar's "Hesap" asks
        # it every few seconds while one runs
        return ok(await call_free(svc().progress.view))

    @handler
    async def nav(request: Request):
        return ok({"pages": await call_free(svc().nav, _user(request))})

    @handler
    async def bugun(request: Request):
        # the morning screen (bugun.py): read from what the service holds - nothing valued, no Bloomberg request
        return ok(await call(svc().bugun.view, _user(request)))

    @handler
    async def header(request: Request):
        return ok(await engine(svc().header_future(_user(request), _lang(request), _since(request), _role(request),
                                                   request.query_params.get("as"))))

    @handler
    async def spot(request: Request):
        return ok(await call(svc().manual_spot, _user(request)))

    # ------------------------------------------------------------------ views
    @handler
    async def view(request: Request):
        show = request.query_params.get("all") in ("1", "true")
        panels = [x for x in (request.query_params.get("panels") or "").split(",") if x][:400] or None
        return ok(await engine(svc().view_future(_user(request), request.path_params["view_id"], show, _lang(request),
                                                 _since(request), panels, _role(request), request.query_params.get("as"))))

    @handler
    async def panels(request: Request):
        # tables of any pages in one request: a launchpad, the side drawer, a pop-out window (see Service.panels_future)
        data = await _body(request)
        return ok(await engine(svc().panels_future(_user(request), data.get("items"), _lang(request), _role(request))))

    # ------------------------------------------------------------------ each user's own arrangement
    @handler
    async def layout(request: Request):
        # launchpads, the side drawer, the favourite pages, the page the dashboard opens on: GET reads, POST replaces
        # the parts it sends
        if request.method == "GET":
            return ok(await call_free(svc().layout, _user(request)))
        return ok(await call_free(svc().set_layout, _user(request), await _body(request)))

    @handler
    async def layout_export(request: Request):
        raw, name = await call_free(svc().export_launchpad, _user(request), request.query_params.get("name"))
        return Response(raw, media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="%s"' % name, "Cache-Control": "no-store"})

    @handler
    async def layout_import(request: Request):
        data = await _body(request)
        return ok(await call_free(svc().import_launchpad, _user(request), data.get("launchpad"), data.get("name")))

    @handler
    async def calc_post(request: Request):
        # each user's calc sheets (calc.py): "eval" brings the boxes on screen up to date, "save" changes a sheet - the
        # sheets are read in a thread, the calculation awaited without holding one
        data = await _body(request)
        fut = await call_free(svc().calcsheets.post, request.path_params["what"], _user(request), data, _lang(request),
                              _role(request))
        return ok(await engine(fut))

    @handler
    async def image(request: Request):
        q = request.query_params
        try:
            index = int(q.get("i", "0"))
        except ValueError:
            index = -1
        raw, mime = await call_free(svc().image, q.get("book", "tto"), q.get("sheet", ""), index)
        return Response(raw, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})

    @handler
    async def client_quote(request: Request):
        # "Kotasyon kopyala": a pricing table's quote for a client as text (``language`` tr / en: ``lang`` is the
        # number format of the page, sent with every request)
        q = request.query_params
        return ok(await call(svc().client_quote, _user(request), q.get("view", ""), q.get("panel", ""), q.get("row"),
                             q.get("part"), q.get("language"), _role(request)))

    @handler
    async def cell(request: Request):
        q = request.query_params
        return ok(await call(svc().cell_info, _user(request), q.get("book", "tto"), q.get("ref", ""), _lang(request),
                             q.get("copy") or None))

    @handler
    async def grid(request: Request):
        # any rectangle of any sheet: the sheet explorer, for administrators only (a page's cells come with the page,
        # a cell's details with /api/cell)
        await call(svc().require_admin, _user(request))
        q = request.query_params
        return ok(await call(svc().grid, _user(request), q.get("book", "tto"), q.get("sheet", ""),
                             q.get("range", "A1:T40"), _lang(request)))

    @handler
    async def sheets(request: Request):
        await call(svc().require_admin, _user(request))
        return ok({"sheets": await call(svc().sheets, request.query_params.get("book", "tto"))})

    # ------------------------------------------------------------------ inputs
    @handler
    async def inputs(request: Request):
        data = await _body(request)
        items = data.get("items")
        if not isinstance(items, list):
            raise ServiceError("items listesi gerekli")
        return ok(await call(svc().set_inputs, _user(request), str(data.get("book", "tto")), items,
                             bool(data.get("adhoc")), _lang(request), bool(data.get("lenient"))))

    @handler
    async def paste(request: Request):
        data = await _body(request)
        return ok(await call(svc().paste, _user(request), str(data.get("book", "tto")), str(data.get("anchor", "")),
                             str(data.get("text", "")), bool(data.get("adhoc")), _lang(request)))

    @handler
    async def reset(request: Request):
        data = await _body(request)
        refs = data.get("refs")
        return ok(await call(svc().reset_inputs, _user(request), str(data.get("book", "tto")),
                             refs if isinstance(refs, list) else None, bool(data.get("shared"))))

    @handler
    async def my_inputs(request: Request):
        return ok(await call_free(svc().my_inputs, _user(request)))

    # ------------------------------------------------------------------ temporary copies of a table
    @handler
    async def copies(request: Request):
        # GET: the user's copies; POST /api/copies/{open|close|inputs|reset} (see Service.copy_action)
        if request.method == "GET":
            return ok(await call_free(svc().copies_of, _user(request)))
        data = await _body(request)
        return ok(await call(svc().copy_action, _user(request), request.path_params.get("what", ""), data, _lang(request)))

    # ------------------------------------------------------------------ scenarios
    @handler
    async def scenarios(request: Request):
        if request.method == "GET":
            return ok({"scenarios": await call_free(svc().scenarios, _user(request))})
        data = await _body(request)
        name = str(data.get("name") or "")
        if request.method == "DELETE":
            return ok(await call_free(svc().delete_scenario, _user(request), name))
        return ok(await call_free(svc().save_scenario, _user(request), name))

    @handler
    async def scenario_load(request: Request):
        data = await _body(request)
        return ok(await call(svc().load_scenario, _user(request), str(data.get("name") or "")))

    # ------------------------------------------------------------------ the columns a user hides
    @handler
    async def columns(request: Request):
        if request.method == "GET":
            return ok(await call_free(svc().columns, _user(request)))
        data = await _body(request)
        # {table, hidden}: the columns hidden; {table, order}: the order of the columns ([] - the sheet's own); both at once
        out: Dict[str, Any] = {}
        if "order" in data:
            out.update(await call_free(svc().set_column_order, _user(request), data.get("table"), data.get("order")))
        if "order" not in data or "hidden" in data:
            out.update(await call_free(svc().set_columns, _user(request), data.get("table"), data.get("hidden")))
        return ok(out)

    # ------------------------------------------------------------------ RET curve
    @handler
    async def ret(request: Request):
        if request.method == "GET":
            return ok(await call(svc().ret))
        data = await _body(request)
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise ServiceError("rows listesi gerekli")
        return ok(await call(svc().set_ret, _user(request), rows, _lang(request)))

    @handler
    async def ret_history(request: Request):
        return ok({"history": await call_free(svc().ret_history)})

    # ------------------------------------------------------------------ the fair value RET (retfair.py)
    @handler
    async def ret_fair(request: Request):
        return ok(await call(svc().retfair.state, _user(request)))

    @handler
    async def ret_fair_tenors(request: Request):
        # the desk's per-tenor settings: {"tenors": [...] | "all", "offset" | "shift" | "from_published" | "base"}
        return ok(await call(svc().retfair.change, _user(request), await _body(request)))

    @handler
    async def ret_fair_settings(request: Request):
        # "Ekstra ayarlar": administrators only
        return ok(await call(svc().retfair.set_settings, _user(request), await _body(request)))

    @handler
    async def ret_fair_flow(request: Request):
        # {"accept": <suggestion id>} / {"remove": <tenor>}
        return ok(await call(svc().retfair.flow, _user(request), await _body(request)))

    @handler
    async def ret_fair_publish(request: Request):
        # "Kopyala ve yayınla": the curve the page copied becomes the desk's RET (``scenario``: the view it came from)
        data = await _body(request)
        return ok(await call(svc().retfair.publish, _user(request), data.get("rows"), data.get("scenario")))

    @handler
    async def ret_fair_view(request: Request):
        # the user's own "Senaryo" of the fair value: {"scenario": "piyasa" | "S1" | "S2" | "S3"}
        return ok(await call(svc().retfair.set_view, _user(request), await _body(request)))

    @handler
    async def ret_position(request: Request):
        # Günlük İşlemler's "Pozisyon ve maliyet": the desk's forwards per RET tenor, today and the last days
        return ok(await call(svc().retfair.position, _user(request)))

    # ------------------------------------------------------------------ blotter
    @handler
    async def blotter(request: Request):
        q = request.query_params
        return ok(await call(svc().blotter, _user(request), q.get("date"), _lang(request), q.get("to")))

    @handler
    async def blotter_export(request: Request):
        q = request.query_params
        raw, name = await call(svc().blotter_export, _user(request), q.get("date"), _lang(request), q.get("to"))
        return Response(raw, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="%s"' % name, "Cache-Control": "no-store"})

    # ------------------------------------------------------------------ what Bloomberg does not know
    @handler
    async def market_unknown(request: Request):
        return ok(await call(svc().market_unknown))

    @handler
    async def market_unknown_export(request: Request):
        raw, name = await call(svc().market_unknown_export)
        return Response(raw, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="%s"' % name, "Cache-Control": "no-store"})

    # ------------------------------------------------------------------ realized volatility · carry
    @handler
    async def vol(request: Request):
        data = await _body(request)
        return ok(await call(svc().vol, _user(request), str(data.get("text", "")), data.get("window", 20)))

    @handler
    async def carry_vol(request: Request):
        if request.method == "POST":
            data = await _body(request)
            return ok(await call(svc().carry_vol, _user(request), str(data.get("kind") or "list"), data.get("window", 60),
                                 str(data.get("text") or "")))
        q = request.query_params
        return ok(await call(svc().carry_vol, _user(request), q.get("kind", "fly"), q.get("window", 60), q.get("text", "")))

    @handler
    async def carry_settings(request: Request):
        if request.method == "POST":
            data = await _body(request)
            return ok(await call(svc().set_carry_settings, _user(request), data.get("path"), data.get("a"), data.get("b")))
        return ok(await call(svc().carry_settings, _user(request)))

    @handler
    async def interp_settings(request: Request):
        # Ayarlar → Eğri interpolasyonu: the user's own choice, Bootstrap (Murex) or PPK basamak
        if request.method == "POST":
            data = await _body(request)
            return ok(await call(svc().set_interp, _user(request), data.get("mode")))
        return ok(await call(svc().interp_settings, _user(request)))

    @handler
    async def spreads(request: Request):
        return ok(await call(svc().spreads, _user(request)))

    # ------------------------------------------------------------------ Spot / FX and FX vol
    @handler
    async def fx_board(request: Request):
        return ok(await call(svc().fx_board, _user(request)))

    @handler
    async def fx_surface(request: Request):
        data = await _body(request)
        return ok(await call(svc().fx_surface, _user(request), data.get("pair"), data.get("model"), data.get("levels")))

    @handler
    async def fx_override(request: Request):
        data = await _body(request)
        if data.get("clear"):
            return ok(await call(svc().fx_override_clear, _user(request), data.get("pair")))
        return ok(await call(svc().fx_override, _user(request), data.get("pair"), data.get("tenor"), data.get("kind"),
                             data.get("value")))

    @handler
    async def fx_monitor(request: Request):
        return ok(await call(svc().fx_monitor, _user(request), request.query_params.get("window", 250)))

    @handler
    async def fx_pair(request: Request):
        q = request.query_params
        return ok(await call(svc().fx_pair, _user(request), q.get("pair"), q.get("tenor", "1M"), q.get("model", "svi")))

    @handler
    async def fx_series(request: Request):
        q = request.query_params
        return ok(await call(svc().fx_series, _user(request), q.get("ticker"), q.get("window", 250), q.get("pair"), q.get("kind"),
                             q.get("tenor")))

    @handler
    async def fx_tenor(request: Request):
        q = request.query_params
        return ok(await call(svc().fx_tenor, _user(request), q.get("pair"), q.get("tenor")))

    @handler
    async def fx_tickers(request: Request):
        if request.method == "POST":
            data = await _body(request)
            if data.get("remove"):
                return ok(await call(svc().fx_ticker_remove, _user(request), data.get("remove")))
            if "source" in data:
                return ok(await call(svc().fx_set_settings, _user(request), data.get("source")))
            return ok(await call(svc().fx_ticker_add, _user(request), data.get("text"), data.get("label", "")))
        return ok(await call(svc().fx_tickers, _user(request)))

    @handler
    async def fx_history(request: Request):
        data = await _body(request)
        return ok(await call(svc().fx_history_sync, _user(request), data.get("pair")))

    # ------------------------------------------------------------------ broker chat
    @handler
    async def broker(request: Request):
        q = request.query_params
        return ok(await call(svc().broker, _user(request), q.get("date"), q.get("to"), q.get("part")))

    @handler
    async def broker_parse(request: Request):
        data = await _body(request)
        return ok(await call(svc().broker_parse, _user(request), str(data.get("text", "")), data.get("date") or None,
                             str(data.get("source") or ""), str(data.get("party") or "")))

    @handler
    async def broker_add(request: Request):
        data = await _body(request)
        return ok(await call(svc().broker_add, _user(request), str(data.get("text", "")), data.get("date") or None,
                             str(data.get("source") or ""), data.get("texts", True) is not False, str(data.get("party") or "")))

    @handler
    async def broker_people(request: Request):
        return ok(await call(svc().broker_people, _user(request)))

    @handler
    async def broker_set_people(request: Request):
        data = await _body(request)
        return ok(await call(svc().broker_set_people, _user(request), data.get("people")))

    @handler
    async def broker_delete(request: Request):
        return ok(await call(svc().broker_delete, _user(request), int(request.path_params["quote_id"])))

    @handler
    async def broker_delete_many(request: Request):
        data = await _body(request)
        return ok(await call(svc().broker_delete_many, _user(request), data.get("ids") or []))

    @handler
    async def broker_reset(request: Request):
        data = await _body(request)
        return ok(await call(svc().broker_reset, _user(request), data.get("date") or None, data.get("key") or None,
                             bool(data.get("undo"))))

    @handler
    async def broker_settings(request: Request):
        data = await _body(request)
        return ok(await call(svc().broker_settings, _user(request), data.get("stale_minutes")))

    @handler
    async def broker_recon(request: Request):
        if request.method == "POST":
            data = await _body(request)
            return ok(await call(svc().broker_recon_set, _user(request), data.get("quote"), str(data.get("action") or ""),
                                 data.get("trade")))
        q = request.query_params
        return ok(await call(svc().broker_recon, _user(request), q.get("date"), q.get("to")))

    @handler
    async def broker_export(request: Request):
        q = request.query_params
        raw, name = await call(svc().broker_export, _user(request), q.get("date"), q.get("to"))
        return Response(raw, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="%s"' % name, "Cache-Control": "no-store"})

    @handler
    async def quote_forward(request: Request):
        return ok(await call(svc().quote_forward, _user(request), await _body(request), _lang(request)))

    @handler
    async def add_forward(request: Request):
        return ok(await call(svc().add_forward, _user(request), await _body(request), _lang(request)))

    @handler
    async def quote_ois(request: Request):
        return ok(await call(svc().quote_ois, _user(request), await _body(request), _lang(request)))

    @handler
    async def add_ois(request: Request):
        return ok(await call(svc().add_ois, _user(request), await _body(request), _lang(request)))

    @handler
    async def ois_market(request: Request):
        return ok(await call(svc().ois_market, _user(request)))

    @handler
    async def quote_bond(request: Request):
        return ok(await call(svc().quote_bond, _user(request), await _body(request), _lang(request)))

    @handler
    async def add_bond(request: Request):
        return ok(await call(svc().add_bond, _user(request), await _body(request), _lang(request)))

    @handler
    async def delete_trade(request: Request):
        return ok(await call(svc().delete_trade, _user(request), int(request.path_params["trade_id"])))

    @handler
    async def edit_trade(request: Request):
        # "Düzenle": the trade changed in place (the same ids) - what the form changed alone moves
        return ok(await call(svc().edit_trade, _user(request), int(request.path_params["trade_id"]), await _body(request),
                             _lang(request)))

    @handler
    async def edit_preview(request: Request):
        # what "Değişikliği kaydet" would make of the edit form - how it is priced, the trade as its quote - nothing saved
        return ok(await call(svc().edit_preview, _user(request), int(request.path_params["trade_id"]), await _body(request),
                             _lang(request)))

    @handler
    async def blotter_templates(request: Request):
        if request.method == "POST":
            data = await _body(request)
            return ok(await call_free(svc().save_trade_template, _user(request), data.get("name"), data.get("kind"),
                                      data.get("spec"), data.get("shared")))
        return ok(await call_free(svc().trade_templates, _user(request)))

    @handler
    async def blotter_template(request: Request):
        tid = request.path_params["tid"]
        if request.method == "DELETE":
            return ok(await call_free(svc().delete_trade_template, _user(request), tid))
        data = await _body(request)                     # what is left out stays as it was (a rename: the name alone)
        return ok(await call_free(svc().save_trade_template, _user(request), data.get("name"), data.get("kind"),
                                  data.get("spec"), data.get("shared"), tid))

    @handler
    async def bulk_preview(request: Request):
        data = await _body(request)
        return ok(await call(svc().bulk_preview, _user(request), data.get("kind"), data.get("text"), data.get("mapping"),
                             data.get("header"), _lang(request)))

    @handler
    async def bulk_save(request: Request):
        data = await _body(request)
        return ok(await call(svc().bulk_save, _user(request), data.get("kind"), data.get("text"), data.get("mapping"),
                             data.get("header"), data.get("rows"), _lang(request)))

    @handler
    async def trade_prefill(request: Request):
        # a price of a page right-clicked ("İşlem gir"): the trade Günlük İşlemler's form is filled with (nothing saved)
        return ok(await call(svc().trade_prefill, _user(request), await _body(request), _lang(request)))

    # ------------------------------------------------------------------ history: closes, meeting pricing, calendar
    def _int(request: Request, name: str, default: Optional[int] = None) -> Optional[int]:
        raw = request.query_params.get(name)
        if raw in (None, ""):
            return default
        try:
            return int(raw)
        except ValueError:
            raise ServiceError("%s bir sayı olmalı" % name)

    @handler
    async def history_status(request: Request):
        return ok(await call_free(svc().history.status))

    @handler
    async def history_sync(request: Request):
        data = await _body(request)
        await call_free(svc().require_user, _user(request))
        return ok(await call(svc().history.request_sync, bool(data.get("recompute"))))

    @handler
    async def history_settings(request: Request):
        data = await _body(request)
        await call_free(svc().require_user, _user(request))
        try:
            return ok(await call(svc().history.set_settings, data))
        except ValueError as exc:
            raise ServiceError(str(exc))

    @handler
    async def history_series(request: Request):
        return ok(await call(svc().history.coverage))

    @handler
    async def history_closes(request: Request):
        return ok(await call(svc().history_closes, _user(request), request.query_params.get("sid")))

    @handler
    async def bond_catalog(request: Request):
        return ok(await call(svc().bond_catalog, _user(request)))

    @handler
    async def watch(request: Request):
        return ok(await call(svc().watch_view, _user(request), request.query_params.get("lang"), request.query_params.get("days") or 60,
                             request.query_params.get("part")))

    @handler
    async def heat(request: Request):
        return ok(await call(svc().heat_view, _user(request), request.query_params.get("basis") or "close", request.query_params.get("lang")))

    @handler
    async def heat_ref(request: Request):
        return ok(await call(svc().heat_ref, _user(request)))

    @handler
    async def dibs_genel(request: Request):
        # DİBS RV · Genel (dibsgenel.py): the trading list on DİBS RV, DİBS ASW and the zero-coupon curve fitted live
        return ok(await call(svc().dibsgenel.view, _user(request), _lang(request)))

    @handler
    async def watch_catalog(request: Request):
        return ok(await call(svc().watch_catalog, _user(request)))

    @handler
    async def watch_action(request: Request):
        data = await _body(request)
        what = request.path_params["what"]
        u = _user(request)
        s = svc()
        subject = data.get("subject") if isinstance(data.get("subject"), dict) else None
        if what == "add":
            return ok(await call(s.watch_add, u, str(data.get("book") or "tto"), str(data.get("ref") or ""),
                                 str(data.get("label") or ""), str(data.get("unit") or ""), subject, str(data.get("hint") or "")))
        if what == "preview":
            return ok(await call(s.watch_preview, u, subject, str(data.get("book") or "tto"), str(data.get("ref") or "")))
        if what == "preset":
            return ok(await call(s.watch_preset, u, str(data.get("group") or "")))
        if what == "remove":
            return ok(await call(s.watch_remove, u, str(data.get("id") or "")))
        if what == "update":
            move = data.get("move")
            return ok(await call(s.watch_update, u, str(data.get("id") or ""), data.get("label"), data.get("unit"),
                                 int(move) if isinstance(move, (int, float)) else None))
        if what == "base":
            return ok(await call(s.watch_base, u, data.get("id") or None))
        if what == "history":
            return ok(await call(s.watch_history, u, subject))
        raise ServiceError("bilinmeyen işlem: %s" % what, 404)

    @handler
    async def alarm_action(request: Request):
        data = await _body(request)
        what = request.path_params["what"]
        u = _user(request)
        s = svc()
        desk = bool(data.get("desk"))                 # the desk's alarm (for everyone): administrators set it
        if what == "add":
            subject = data.get("subject") if isinstance(data.get("subject"), dict) else None
            return ok(await call(s.desk_alarm_add if desk else s.alarm_add, u, str(data.get("book") or "tto"), str(data.get("ref") or ""),
                                 str(data.get("op") or ""), data.get("level"), str(data.get("label") or ""), str(data.get("note") or ""),
                                 subject, str(data.get("mode") or "level"), data.get("minutes"), data.get("days")))
        if what == "remove":
            return ok(await call(s.desk_alarm_remove if desk else s.alarm_remove, u, str(data.get("id") or "")))
        if what == "rearm":
            return ok(await call(s.desk_alarm_rearm if desk else s.alarm_rearm, u, str(data.get("id") or ""), data.get("level")))
        # the desk's alarms: "Gördüm, ben bakıyorum", a mute (anyone), the settings (administrators)
        if what == "ack":
            return ok(await call(s.desk_alarm_ack, u, data.get("seq")))
        if what == "mute":
            return ok(await call(s.desk_alarm_mute, u, data.get("alarm"), data.get("minutes")))
        if what == "settings":
            return ok(await call(s.desk_alarm_settings, u, data.get("values")))
        raise ServiceError("bilinmeyen işlem: %s" % what, 404)

    @handler
    async def alarms_fired(request: Request):
        try:
            since = int(request.query_params.get("since") or 0)
        except ValueError:
            since = 0
        return ok(await call_free(svc().alarms_fired, _user(request), since, request.query_params.get("desk")))

    @handler
    async def notes(request: Request):
        data = await _body(request)
        return ok(await call(svc().notes_set, _user(request), str(data.get("text") or "")))

    @handler
    async def bond_flag(request: Request):
        data = await _body(request)
        return ok(await call(svc().bond_flag, _user(request), str(data.get("isin") or ""), bool(data.get("on"))))

    @handler
    async def bond_list_add(request: Request):
        data = await _body(request)
        values = data.get("values") or []
        return ok(await call(svc().bond_list_add, _user(request), values if isinstance(values, list) else [values]))

    @handler
    async def bond_list_remove(request: Request):
        data = await _body(request)
        return ok(await call(svc().bond_list_remove, _user(request), str(data.get("isin") or "")))

    @handler
    async def bond_card(request: Request):
        return ok(await call(svc().bond_card, _user(request), request.path_params["isin"]))

    @handler
    async def list_add(request: Request):
        data = await _body(request)
        return ok(await call(svc().list_add, _user(request), str(data.get("book") or "tto"), str(data.get("list") or ""),
                             data.get("values") or []))

    @handler
    async def sources(request: Request):
        if request.method == "POST":
            data = await _body(request)
            return ok(await call(svc().set_sources, _user(request), data.get("lists") or {}))
        return ok(await call(svc().sources))

    @handler
    async def history_matrix(request: Request):
        return ok(await call(svc().history.matrix, request.query_params.get("asof") or None))

    @handler
    async def history_mpc(request: Request):
        return ok(await call(svc().history.mpc, _int(request, "days"), _int(request, "n", 16)))

    @handler
    async def calendar(request: Request):
        if request.method == "GET":
            return ok(await call(svc().history.calendar))
        data = await _body(request)
        dates = data.get("dates")
        if not isinstance(dates, list):
            raise ServiceError("dates listesi gerekli")
        # "version": the calendar the list was edited from - a save over a calendar that changed since is refused (409)
        version = data.get("version")
        return ok(await call(svc().history.set_calendar, _user(request), dates, bool(data.get("roll")),
                             str(version) if version not in (None, "") else None))

    @handler
    async def holidays(request: Request):
        if request.method == "GET":
            return ok(await call(svc().holidays))
        data = await _body(request)
        items = data.get("items")
        if not isinstance(items, list):
            raise ServiceError("items listesi gerekli")
        # {"ccy": "USD", "items": [...]}: one currency's list (TRY when left out)
        return ok(await call(svc().set_holidays, _user(request), items, data.get("ccy") or "TRY"))

    @handler
    async def calendar_preview(request: Request):
        data = await _body(request)
        current, dates = data.get("current"), data.get("dates")
        if not isinstance(current, list) or not isinstance(dates, list):
            raise ServiceError("current ve dates listeleri gerekli")
        return ok(await call(svc().history.preview_calendar, current, dates, str(data.get("mode") or "correct")))

    # ------------------------------------------------------------------ the desk's own: reports, chat, agenda (desk.py)
    @handler
    async def desk_state(request: Request):
        return ok(await call(svc().desk.state, _user(request), request.query_params.get("seen")))

    @handler
    async def feedback(request: Request):
        if request.method == "POST":
            data = await _body(request)
            return ok(await call(svc().desk.report, _user(request), data.get("kind"), data.get("text"), data.get("page"),
                                 data.get("title")))
        return ok(await call(svc().desk.reports, _user(request)))

    @handler
    async def feedback_done(request: Request):
        data = await _body(request)
        return ok(await call(svc().desk.report_done, _user(request), request.path_params["fid"], data.get("done", True)))

    @handler
    async def social(request: Request):
        if request.method == "POST":
            data = await _body(request)
            return ok(await call(svc().desk.say, _user(request), data.get("text")))
        q = request.query_params
        return ok(await call(svc().desk.chat, _user(request), q.get("before"), q.get("since")))

    @handler
    async def social_delete(request: Request):
        return ok(await call(svc().desk.unsay, _user(request), request.path_params["mid"]))

    @handler
    async def agenda(request: Request):
        if request.method == "POST":
            data = await _body(request)
            return ok(await call(svc().desk.add, _user(request), data.get("day"), data.get("time"), data.get("text"),
                                 data.get("deadline"), data.get("shared", True)))
        return ok(await call(svc().desk.agenda, _user(request)))

    @handler
    async def agenda_item(request: Request):
        if request.method == "DELETE":
            return ok(await call(svc().desk.remove, _user(request), request.path_params["aid"]))
        data = await _body(request)
        return ok(await call(svc().desk.mark, _user(request), request.path_params["aid"], data.get("done", True)))

    @handler
    async def agenda_rules(request: Request):
        data = await _body(request)
        return ok(await call(svc().desk.add_rule, _user(request), data.get("repeat"), data.get("time"), data.get("text"),
                             data.get("deadline"), data.get("shared", True), data.get("weekdays"), data.get("start"),
                             data.get("end")))

    @handler
    async def agenda_rule(request: Request):
        rid = request.path_params["rid"]
        if request.method == "DELETE":
            return ok(await call(svc().desk.remove_rule, _user(request), rid))
        data = await _body(request)
        return ok(await call(svc().desk.edit_rule, _user(request), rid, data.get("repeat"), data.get("time"), data.get("text"),
                             data.get("deadline"), data.get("weekdays"), data.get("start"), data.get("end")))

    @handler
    async def agenda_rule_action(request: Request):
        rid, what = request.path_params["rid"], request.path_params["what"]
        data = await _body(request)
        desk = svc().desk
        if what == "done":                    # "Bugün tamam" (a day of it; done false: not done after all)
            return ok(await call(desk.rule_done, _user(request), rid, data.get("day"), data.get("done", True)))
        if what == "snooze":                  # "Ertele 10 dk" (for oneself)
            return ok(await call(desk.snooze, _user(request), rid, data.get("day")))
        if what == "pause":                   # paused / going on again
            return ok(await call(desk.pause_rule, _user(request), rid, data.get("paused", True)))
        raise ServiceError("bilinmeyen işlem: %s" % what, 404)

    # ------------------------------------------------------------------ Trades (tradebook.py): the desk's and one's own
    # Every call needs a session; a trader's own trades answer only their owner (any other user, an administrator too,
    # gets the 404 of a trade that does not exist).  Nothing here values a trade but "MTM yenile", a close and a swap's
    # "Kuponlar".
    def _trade_lang(request: Request) -> str:
        return _lang(request) or svc().settings.locale

    @handler
    async def trades(request: Request):
        book = svc().tradebook
        if request.method == "GET":                # a tab: ?scope=desk | personal
            return ok(await call_free(book.listing, _user(request), request.query_params.get("scope")))
        return ok(await call(book.add, _user(request), await _body(request), _trade_lang(request)))

    @handler
    async def trades_check(request: Request):
        # the form read as saving reads it (dates of the shortcuts, the trade in the desk's words) - nothing saved
        return ok(await call(svc().tradebook.check, _user(request), await _body(request), _trade_lang(request)))

    @handler
    async def trades_defaults(request: Request):
        q = request.query_params
        return ok(await call(svc().tradebook.defaults, _user(request), q.get("product"), q.get("pair"), q.get("trade_date"),
                             q.get("expiry"), q.get("fra"), q.get("isin"), q.get("structure")))

    @handler
    async def trades_dv01(request: Request):
        # the nominal of a DV01 typed (rounded to 5 mn) or the DV01 of a nominal: POST the form with ``size``, or GET one
        # instrument's fields with ``dv01`` / ``notional`` in the query
        if request.method == "GET":
            raw: Dict[str, Any] = dict(request.query_params)
            raw.pop("lang", None)
            raw["size"] = [{"leg": None, "dv01": raw.pop("dv01", None), "notional": raw.pop("notional", None),
                            "dv01_ccy": raw.get("dv01_ccy")}]
        else:
            raw = await _body(request)
        return ok(await call(svc().tradebook.size, _user(request), raw, _trade_lang(request)))

    @handler
    async def trades_mtm(request: Request):
        data = await _body(request)
        return ok(await call(svc().tradebook.mtm, _user(request), data.get("scope")))

    @handler
    async def trades_log(request: Request):
        return ok(await call_free(svc().tradebook.recent, _user(request), request.query_params.get("scope")))

    @handler
    async def trades_quant(request: Request):
        # "Quant'tan": per family, the trades taken from its lines that the user sees (the desk's and their own)
        from . import tradequant
        return ok(await call(tradequant.table, svc().tradebook, _user(request)))

    @handler
    async def trades_from_quant(request: Request):
        # "İşleme al": a quant line (?id=) as the Trades form, filled - nothing saved
        from . import tradequant
        q = request.query_params
        return ok(await call(tradequant.prefill, svc(), _user(request), q.get("id"), q.get("scope") or "personal",
                             _trade_lang(request)))

    @handler
    async def trade_one(request: Request):
        tid = request.path_params["tid"]
        if request.method == "DELETE":               # (its alarms follow on the calculation thread)
            return ok(await call(svc().tradebook.remove, _user(request), tid))
        return ok(await call(svc().tradebook.edit, _user(request), tid, await _body(request), _trade_lang(request)))

    @handler
    async def trade_log(request: Request):
        return ok(await call_free(svc().tradebook.log, _user(request), request.path_params["tid"]))

    @handler
    async def trade_coupons(request: Request):
        # "Kuponlar": a swap's schedule and the coupons it has paid / received, valued now (one's own trade: its owner only)
        return ok(await call(svc().tradebook.coupons, _user(request), request.path_params["tid"]))

    @handler
    async def trade_action(request: Request):
        tid, what = request.path_params["tid"], request.path_params["what"]
        data = await _body(request)
        book = svc().tradebook
        if what == "close":                   # a close date and price: to the closed list, with its realised P&L
            return ok(await call(book.close, _user(request), tid, data.get("close_date"), data.get("close_price"),
                                 _trade_lang(request)))
        if what == "reopen":                  # the close taken back (its alarms again)
            return ok(await call(book.reopen, _user(request), tid))
        raise ServiceError("bilinmeyen işlem: %s" % what, 404)

    # ------------------------------------------------------------------ quant signals (quant.py)
    @handler
    async def quant_get(request: Request):
        # (every line says whether Trades can book it: "İşleme al" - tradequant.mark)
        from . import tradequant
        return ok(tradequant.mark(await call(svc().quant.view, request.path_params["what"], _user(request), dict(request.query_params))))

    @handler
    async def quant_post(request: Request):
        data = await _body(request)
        return ok(await call(svc().quant.action, request.path_params["what"], _user(request), data))

    # ------------------------------------------------------------------ live updates (SSE)
    async def events(request: Request):
        loop = asyncio.get_running_loop()
        q: "asyncio.Queue[int]" = asyncio.Queue(maxsize=8)

        def push(gen: int) -> None:
            def put():
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(gen)
            try:
                loop.call_soon_threadsafe(put)
            except RuntimeError:
                pass

        service = svc()
        who = _user(request)
        token = request.scope.get("tto_token")              # (presence: this browser holds its stream)
        # the counters of the desk's own corner go along (a chat message makes no new generation) - the reports' one
        # to an administrator only
        admin = await call_free(service.desk.is_admin, who)

        def message(gen: int) -> str:
            # (the quant signals' counters: the last alert's number, the version of the results - see quant.Quant.counters;
            # Broker Chat's changes: a box of its board asks again on those, not on every generation; the Trades page's
            # lists - the desk's and this user's own, nobody else's - ride with the desk corner's counters; who is
            # online: the counts of the top bar's chip and the version its list follows)
            desk = service.desk.counters(admin)
            book = getattr(service, "tradebook", None)
            if book is not None:
                desk["trades"] = book.counter(who)
            return "data: %s\n\n" % json.dumps({"gen": gen, "desk": desk, "quant": service.quant.counters(),
                                                "broker": service.broker_changes, "presence": service.presence.counters()})

        async def stream():
            service.add_listener(push)
            service.stream(who, 1, token)
            try:
                yield message(service.gen)
                while True:
                    try:
                        gen = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield message(gen)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                    if await request.is_disconnected():
                        break
            finally:
                service.remove_listener(push)
                service.stream(who, -1, token)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    routes = [
        Route("/", index),
        Route("/api/auth", auth_state),
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/account-request", account_request, methods=["POST"]),
        Route("/api/setup", setup, methods=["POST"]),
        Route("/api/password", password, methods=["POST"]),
        Route("/api/admin/users", admin_users),
        Route("/api/admin/users/{action}", admin_action, methods=["POST"]),
        Route("/api/admin/backup", admin_backup, methods=["GET", "POST"]),
        Route("/api/admin/backup/now", admin_backup_now, methods=["POST"]),
        Route("/api/users", users),
        Route("/api/presence", presence, methods=["GET", "POST"]),
        Route("/api/status", status),
        Route("/api/progress", progress),
        Route("/api/nav", nav),
        Route("/api/bugun", bugun),
        Route("/api/header", header),
        Route("/api/spot", spot),
        Route("/api/view/{view_id}", view),
        Route("/api/panels", panels, methods=["POST"]),
        Route("/api/layout", layout, methods=["GET", "POST"]),
        Route("/api/layout/export", layout_export),
        Route("/api/layout/import", layout_import, methods=["POST"]),
        Route("/api/calc/{what}", calc_post, methods=["POST"]),
        Route("/api/image", image),
        Route("/api/cell", cell),
        Route("/api/quote", client_quote),
        Route("/api/grid", grid),
        Route("/api/sheets", sheets),
        Route("/api/inputs", inputs, methods=["POST"]),
        Route("/api/paste", paste, methods=["POST"]),
        Route("/api/reset", reset, methods=["POST"]),
        Route("/api/my-inputs", my_inputs),
        Route("/api/copies", copies),
        Route("/api/copies/{what}", copies, methods=["POST"]),
        Route("/api/scenarios", scenarios, methods=["GET", "POST", "DELETE"]),
        Route("/api/scenarios/load", scenario_load, methods=["POST"]),
        Route("/api/columns", columns, methods=["GET", "POST"]),
        Route("/api/ret", ret, methods=["GET", "POST"]),
        Route("/api/ret/history", ret_history),
        Route("/api/ret/fair", ret_fair),
        Route("/api/ret/fair/tenors", ret_fair_tenors, methods=["POST"]),
        Route("/api/ret/fair/settings", ret_fair_settings, methods=["POST"]),
        Route("/api/ret/fair/flow", ret_fair_flow, methods=["POST"]),
        Route("/api/ret/fair/publish", ret_fair_publish, methods=["POST"]),
        Route("/api/ret/fair/view", ret_fair_view, methods=["POST"]),
        Route("/api/ret/position", ret_position),
        Route("/api/market/unknown", market_unknown),
        Route("/api/market/unknown/export", market_unknown_export),
        Route("/api/vol", vol, methods=["POST"]),
        Route("/api/vol/carry", carry_vol, methods=["GET", "POST"]),
        Route("/api/carry", carry_settings, methods=["GET", "POST"]),
        Route("/api/interp", interp_settings, methods=["GET", "POST"]),
        Route("/api/spreads", spreads),
        Route("/api/broker", broker),
        Route("/api/broker", broker_add, methods=["POST"]),
        Route("/api/broker/parse", broker_parse, methods=["POST"]),
        Route("/api/broker/people", broker_people),
        Route("/api/broker/people", broker_set_people, methods=["POST"]),
        Route("/api/broker/export", broker_export),
        Route("/api/broker/delete", broker_delete_many, methods=["POST"]),
        Route("/api/broker/reset", broker_reset, methods=["POST"]),
        Route("/api/broker/recon", broker_recon, methods=["GET", "POST"]),
        Route("/api/broker/settings", broker_settings, methods=["POST"]),
        Route("/api/broker/{quote_id:int}", broker_delete, methods=["DELETE"]),
        Route("/api/blotter", blotter),
        Route("/api/blotter/export", blotter_export),
        Route("/api/blotter/quote/forward", quote_forward, methods=["POST"]),
        Route("/api/blotter/forward", add_forward, methods=["POST"]),
        Route("/api/blotter/quote/ois", quote_ois, methods=["POST"]),
        Route("/api/blotter/ois", add_ois, methods=["POST"]),
        Route("/api/blotter/ois-market", ois_market),
        Route("/api/blotter/quote/bond", quote_bond, methods=["POST"]),
        Route("/api/blotter/bond", add_bond, methods=["POST"]),
        Route("/api/blotter/trade/{trade_id:int}", delete_trade, methods=["DELETE"]),
        Route("/api/blotter/trade/{trade_id:int}", edit_trade, methods=["POST"]),
        Route("/api/blotter/trade/{trade_id:int}/preview", edit_preview, methods=["POST"]),
        Route("/api/blotter/templates", blotter_templates, methods=["GET", "POST"]),
        Route("/api/blotter/templates/{tid:int}", blotter_template, methods=["POST", "DELETE"]),
        Route("/api/blotter/bulk/preview", bulk_preview, methods=["POST"]),
        Route("/api/blotter/bulk", bulk_save, methods=["POST"]),
        Route("/api/trade/prefill", trade_prefill, methods=["POST"]),
        Route("/api/history/status", history_status),
        Route("/api/history/sync", history_sync, methods=["POST"]),
        Route("/api/history/settings", history_settings, methods=["POST"]),
        Route("/api/sources", sources, methods=["GET", "POST"]),
        Route("/api/bonds/catalog", bond_catalog),
        Route("/api/list/add", list_add, methods=["POST"]),
        Route("/api/bonds/flag", bond_flag, methods=["POST"]),
        Route("/api/bonds/list/add", bond_list_add, methods=["POST"]),
        Route("/api/bonds/list/remove", bond_list_remove, methods=["POST"]),
        Route("/api/watch", watch),
        Route("/api/watch/catalog", watch_catalog),
        Route("/api/heat", heat),
        Route("/api/heat/ref", heat_ref, methods=["POST"]),
        Route("/api/dibs/genel", dibs_genel),
        Route("/api/watch/{what}", watch_action, methods=["POST"]),
        Route("/api/alarms/fired", alarms_fired),
        Route("/api/alarms/{what}", alarm_action, methods=["POST"]),
        Route("/api/notes", notes, methods=["POST"]),
        Route("/api/bond/{isin}", bond_card),
        Route("/api/history/series", history_series),
        Route("/api/history/matrix", history_matrix),
        Route("/api/history/closes", history_closes),
        Route("/api/history/mpc", history_mpc),
        Route("/api/calendar", calendar, methods=["GET", "POST"]),
        Route("/api/holidays", holidays, methods=["GET", "POST"]),
        Route("/api/calendar/preview", calendar_preview, methods=["POST"]),
        Route("/api/fx/board", fx_board),
        Route("/api/fx/surface", fx_surface, methods=["POST"]),
        Route("/api/fx/override", fx_override, methods=["POST"]),
        Route("/api/fx/monitor", fx_monitor),
        Route("/api/fx/pair", fx_pair),
        Route("/api/fx/series", fx_series),
        Route("/api/fx/tenor", fx_tenor),
        Route("/api/fx/tickers", fx_tickers, methods=["GET", "POST"]),
        Route("/api/fx/history", fx_history, methods=["POST"]),
        Route("/api/events", events),
        Route("/api/desk", desk_state),
        Route("/api/feedback", feedback, methods=["GET", "POST"]),
        Route("/api/feedback/{fid:int}", feedback_done, methods=["POST"]),
        Route("/api/social", social, methods=["GET", "POST"]),
        Route("/api/social/{mid:int}", social_delete, methods=["DELETE"]),
        Route("/api/agenda", agenda, methods=["GET", "POST"]),
        Route("/api/agenda/rules", agenda_rules, methods=["POST"]),
        Route("/api/agenda/rules/{rid:int}", agenda_rule, methods=["POST", "DELETE"]),
        Route("/api/agenda/rules/{rid:int}/{what}", agenda_rule_action, methods=["POST"]),
        Route("/api/agenda/{aid:int}", agenda_item, methods=["POST", "DELETE"]),
        Route("/api/trades", trades, methods=["GET", "POST"]),
        Route("/api/trades/check", trades_check, methods=["POST"]),
        Route("/api/trades/defaults", trades_defaults),
        Route("/api/trades/dv01", trades_dv01, methods=["GET", "POST"]),
        Route("/api/trades/mtm", trades_mtm, methods=["POST"]),
        Route("/api/trades/log", trades_log),
        Route("/api/trades/quant", trades_quant),
        Route("/api/trades/from-quant", trades_from_quant),
        Route("/api/trades/{tid:int}", trade_one, methods=["POST", "DELETE"]),
        Route("/api/trades/{tid:int}/log", trade_log),
        Route("/api/trades/{tid:int}/coupons", trade_coupons),
        Route("/api/trades/{tid:int}/{what}", trade_action, methods=["POST"]),
        Route("/api/quant/{what}", quant_get),
        Route("/api/quant/{what}", quant_post, methods=["POST"]),
        Mount("/static", app=_Static(directory=STATIC), name="static"),
    ]

    async def on_startup():
        if state["service"] is None:
            state["service"] = await run_in_threadpool(Service, settings)
            try:
                print(state["service"].describe(), flush=True)
            except Exception:  # noqa: BLE001 - a console that cannot print must not stop the start
                pass
        state["service"].start()

    async def on_shutdown():
        if state["service"] is not None:
            await run_in_threadpool(state["service"].stop)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        await on_startup()
        try:
            yield
        finally:
            await on_shutdown()

    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(_SessionGate, service=lambda: state["service"])
    app.state.get_service = svc
    return app
