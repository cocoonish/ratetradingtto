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


class _Static(StaticFiles):
    """Static files that the browser always revalidates (so an updated dashboard is picked up at once)."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _user(request: Request) -> Optional[str]:
    """The signed-in user of the request (set by the session gate; ``None`` only on the sign-in routes)."""
    return request.scope.get("tto_user")


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
        user = svc.session_user(token) if (svc is not None and token) else None
        scope["tto_user"] = user
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


def create_app(service: Optional[Service] = None, settings: Optional[Settings] = None) -> Starlette:
    state: Dict[str, Any] = {"service": service}

    def svc() -> Service:
        return state["service"]

    async def call(fn, *args, **kw):
        return await run_in_threadpool(fn, *args, **kw)

    def ok(data: Any) -> JSONResponse:
        return JSONResponse(data)

    def handler(fn):
        async def wrapped(request: Request):
            try:
                return await fn(request)
            except ServiceError as exc:
                return JSONResponse({"error": str(exc)}, status_code=exc.status)
            except Exception as exc:  # noqa: BLE001 - never leak a traceback to the browser
                return JSONResponse({"error": "sunucu hatası: %s" % (str(exc)[:300] or type(exc).__name__)},
                                    status_code=500)
        return wrapped

    # ------------------------------------------------------------------ pages
    async def index(request: Request):
        return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------------ sign-in, accounts
    def signed_in(request: Request, token: str, me: Dict[str, Any]) -> JSONResponse:
        resp = JSONResponse(me)
        resp.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, path="/", httponly=True, samesite="strict",
                        secure=request.url.scheme == "https")
        return resp

    @handler
    async def auth_state(request: Request):
        return ok(await call(svc().auth_state, _user(request), auth.is_local(_ip(request))))

    @handler
    async def login(request: Request):
        data = await _body(request)
        token, me = await call(svc().authenticate, data.get("name"), data.get("password"), _ip(request))
        return signed_in(request, token, me)

    @handler
    async def logout(request: Request):
        resp = JSONResponse(await call(svc().logout, request.scope.get("tto_token")))
        resp.delete_cookie(auth.COOKIE, path="/")
        return resp

    @handler
    async def account_request(request: Request):
        data = await _body(request)
        return ok(await call(svc().request_account, data.get("name"), data.get("password"), data.get("note")))

    @handler
    async def setup(request: Request):
        data = await _body(request)
        token, me = await call(svc().setup_admin, data.get("name"), data.get("password"), auth.is_local(_ip(request)),
                               _ip(request))
        return signed_in(request, token, me)

    @handler
    async def password(request: Request):
        data = await _body(request)
        return ok(await call(svc().change_password, _user(request), data.get("old"), data.get("new"),
                             request.scope.get("tto_token")))

    @handler
    async def admin_users(request: Request):
        return ok(await call(svc().accounts, _user(request)))

    @handler
    async def admin_action(request: Request):
        data = await _body(request)
        return ok(await call(svc().admin_action, _user(request), request.path_params["action"], data,
                             request.scope.get("tto_token")))

    # ------------------------------------------------------------------ session / status

    @handler
    async def users(request: Request):
        return ok({"users": await call(svc().store.users)})

    @handler
    async def status(request: Request):
        return ok(await call(svc().status))

    @handler
    async def nav(request: Request):
        return ok({"pages": await call(svc().nav)})

    @handler
    async def header(request: Request):
        return ok(await call(svc().header, _user(request), _lang(request)))

    @handler
    async def spot(request: Request):
        return ok(await call(svc().manual_spot, _user(request)))

    # ------------------------------------------------------------------ views
    @handler
    async def view(request: Request):
        show = request.query_params.get("all") in ("1", "true")
        return ok(await call(svc().view, _user(request), request.path_params["view_id"], show, _lang(request)))

    @handler
    async def image(request: Request):
        q = request.query_params
        try:
            index = int(q.get("i", "0"))
        except ValueError:
            index = -1
        raw, mime = await call(svc().image, q.get("book", "tto"), q.get("sheet", ""), index)
        return Response(raw, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})

    @handler
    async def cell(request: Request):
        q = request.query_params
        return ok(await call(svc().cell_info, _user(request), q.get("book", "tto"), q.get("ref", ""), _lang(request)))

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
        return ok(await call(svc().my_inputs, _user(request)))

    # ------------------------------------------------------------------ scenarios
    @handler
    async def scenarios(request: Request):
        if request.method == "GET":
            return ok({"scenarios": await call(svc().scenarios, _user(request))})
        data = await _body(request)
        name = str(data.get("name") or "")
        if request.method == "DELETE":
            return ok(await call(svc().delete_scenario, _user(request), name))
        return ok(await call(svc().save_scenario, _user(request), name))

    @handler
    async def scenario_load(request: Request):
        data = await _body(request)
        return ok(await call(svc().load_scenario, _user(request), str(data.get("name") or "")))

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
        return ok({"history": await call(svc().ret_history)})

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
        return ok(await call(svc().broker, _user(request), q.get("date"), q.get("to")))

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
        return ok(await call(svc().history.status))

    @handler
    async def history_sync(request: Request):
        data = await _body(request)
        svc().require_user(_user(request))
        return ok(await call(svc().history.request_sync, bool(data.get("recompute"))))

    @handler
    async def history_settings(request: Request):
        data = await _body(request)
        svc().require_user(_user(request))
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
        return ok(await call(svc().watch_view, _user(request), request.query_params.get("lang"), request.query_params.get("days") or 60))

    @handler
    async def heat(request: Request):
        return ok(await call(svc().heat_view, _user(request), request.query_params.get("basis") or "close", request.query_params.get("lang")))

    @handler
    async def heat_ref(request: Request):
        return ok(await call(svc().heat_ref, _user(request)))

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
        if what == "add":
            subject = data.get("subject") if isinstance(data.get("subject"), dict) else None
            return ok(await call(s.alarm_add, u, str(data.get("book") or "tto"), str(data.get("ref") or ""),
                                 str(data.get("op") or ""), data.get("level"), str(data.get("label") or ""), str(data.get("note") or ""),
                                 subject, str(data.get("mode") or "level"), data.get("minutes"), data.get("days")))
        if what == "remove":
            return ok(await call(s.alarm_remove, u, str(data.get("id") or "")))
        if what == "rearm":
            return ok(await call(s.alarm_rearm, u, str(data.get("id") or ""), data.get("level")))
        raise ServiceError("bilinmeyen işlem: %s" % what, 404)

    @handler
    async def alarms_fired(request: Request):
        try:
            since = int(request.query_params.get("since") or 0)
        except ValueError:
            since = 0
        return ok(await call(svc().alarms_fired, _user(request), since))

    @handler
    async def notes(request: Request):
        data = await _body(request)
        return ok(await call(svc().notes_set, _user(request), str(data.get("text") or "")))

    @handler
    async def bond_flag(request: Request):
        data = await _body(request)
        return ok(await call(svc().bond_flag, _user(request), str(data.get("isin") or ""), bool(data.get("on"))))

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
        return ok(await call(svc().history.set_calendar, _user(request), dates, bool(data.get("roll"))))

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
        # the counters of the desk's own corner go along (a chat message makes no new generation) - the reports' one
        # to an administrator only
        admin = await call(service.desk.is_admin, _user(request))
        service.add_listener(push)

        def message(gen: int) -> str:
            return "data: %s\n\n" % json.dumps({"gen": gen, "desk": service.desk.counters(admin)})

        async def stream():
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
        Route("/api/users", users),
        Route("/api/status", status),
        Route("/api/nav", nav),
        Route("/api/header", header),
        Route("/api/spot", spot),
        Route("/api/view/{view_id}", view),
        Route("/api/image", image),
        Route("/api/cell", cell),
        Route("/api/grid", grid),
        Route("/api/sheets", sheets),
        Route("/api/inputs", inputs, methods=["POST"]),
        Route("/api/paste", paste, methods=["POST"]),
        Route("/api/reset", reset, methods=["POST"]),
        Route("/api/my-inputs", my_inputs),
        Route("/api/scenarios", scenarios, methods=["GET", "POST", "DELETE"]),
        Route("/api/scenarios/load", scenario_load, methods=["POST"]),
        Route("/api/ret", ret, methods=["GET", "POST"]),
        Route("/api/ret/history", ret_history),
        Route("/api/market/unknown", market_unknown),
        Route("/api/market/unknown/export", market_unknown_export),
        Route("/api/vol", vol, methods=["POST"]),
        Route("/api/vol/carry", carry_vol, methods=["GET", "POST"]),
        Route("/api/carry", carry_settings, methods=["GET", "POST"]),
        Route("/api/spreads", spreads),
        Route("/api/broker", broker),
        Route("/api/broker", broker_add, methods=["POST"]),
        Route("/api/broker/parse", broker_parse, methods=["POST"]),
        Route("/api/broker/people", broker_people),
        Route("/api/broker/people", broker_set_people, methods=["POST"]),
        Route("/api/broker/export", broker_export),
        Route("/api/broker/delete", broker_delete_many, methods=["POST"]),
        Route("/api/broker/reset", broker_reset, methods=["POST"]),
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
        Route("/api/history/status", history_status),
        Route("/api/history/sync", history_sync, methods=["POST"]),
        Route("/api/history/settings", history_settings, methods=["POST"]),
        Route("/api/sources", sources, methods=["GET", "POST"]),
        Route("/api/bonds/catalog", bond_catalog),
        Route("/api/list/add", list_add, methods=["POST"]),
        Route("/api/bonds/flag", bond_flag, methods=["POST"]),
        Route("/api/watch", watch),
        Route("/api/watch/catalog", watch_catalog),
        Route("/api/heat", heat),
        Route("/api/heat/ref", heat_ref, methods=["POST"]),
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
        Route("/api/agenda/{aid:int}", agenda_item, methods=["POST", "DELETE"]),
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
