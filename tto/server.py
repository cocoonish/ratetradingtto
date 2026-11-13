"""HTTP layer (Starlette): JSON API, server-sent events and the static single-page app."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional
from urllib.parse import unquote

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .config import Settings
from .service import Service, ServiceError

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class _Static(StaticFiles):
    """Static files that the browser always revalidates (so an updated dashboard is picked up at once)."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _user(request: Request) -> Optional[str]:
    raw = request.headers.get("x-tto-user") or request.query_params.get("user")
    if not raw:
        return None
    return unquote(raw)


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

    # ------------------------------------------------------------------ session / status
    @handler
    async def login(request: Request):
        data = await _body(request)
        return ok(await call(svc().login, str(data.get("name") or "")))

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
        q = request.query_params
        return ok(await call(svc().grid, _user(request), q.get("book", "tto"), q.get("sheet", ""),
                             q.get("range", "A1:T40"), _lang(request)))

    @handler
    async def sheets(request: Request):
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
        return ok(await call(svc().blotter, _user(request), request.query_params.get("date"), _lang(request)))

    @handler
    async def blotter_export(request: Request):
        raw, name = await call(svc().blotter_export, _user(request), request.query_params.get("date"), _lang(request))
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
        service.add_listener(push)

        async def stream():
            try:
                yield "data: %s\n\n" % json.dumps({"gen": service.gen})
                while True:
                    try:
                        gen = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield "data: %s\n\n" % json.dumps({"gen": gen})
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
        Route("/api/login", login, methods=["POST"]),
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
        Route("/api/blotter", blotter),
        Route("/api/blotter/export", blotter_export),
        Route("/api/blotter/quote/forward", quote_forward, methods=["POST"]),
        Route("/api/blotter/forward", add_forward, methods=["POST"]),
        Route("/api/blotter/quote/ois", quote_ois, methods=["POST"]),
        Route("/api/blotter/ois", add_ois, methods=["POST"]),
        Route("/api/blotter/ois-market", ois_market),
        Route("/api/blotter/bond", add_bond, methods=["POST"]),
        Route("/api/blotter/trade/{trade_id:int}", delete_trade, methods=["DELETE"]),
        Route("/api/history/status", history_status),
        Route("/api/history/sync", history_sync, methods=["POST"]),
        Route("/api/history/settings", history_settings, methods=["POST"]),
        Route("/api/history/series", history_series),
        Route("/api/history/matrix", history_matrix),
        Route("/api/history/mpc", history_mpc),
        Route("/api/calendar", calendar, methods=["GET", "POST"]),
        Route("/api/events", events),
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
    app.state.get_service = svc
    return app
