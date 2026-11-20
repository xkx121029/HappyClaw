"""FastAPI app factory."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response

from octop.api.middleware.jwt_auth import install as install_jwt_auth
from octop.api.openapi_meta import API_DESCRIPTION, OPENAPI_TAGS, configure_openapi
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from octop.infra.utils.locale import resolve_request_locale

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RouterMount:
    router: Any
    prefix: str
    tags: Sequence[str]


# Multi-account surfaces are no longer mounted. Their prefixes still collide
# with live routers (``/api/users/{user_id}`` would answer ``roles`` with 422)
# and with the GET-only SPA catch-all (405), so answer them explicitly.
_RETIRED_MULTI_USER_PREFIXES = (
    "/users/roles",
    "/users/invites",
    "/auth/invite",
    "/auth/ldap",
    "/auth/oidc",
    "/auth/oauth",
    "/auth/mfa",
    "/auth/passkey",
)


def _retired_multi_user_router() -> Any:
    from fastapi import APIRouter  # noqa: PLC0415

    router = APIRouter(include_in_schema=False)
    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]

    async def retired_multi_user_endpoint(rest: str = "") -> None:
        _ = rest
        raise OctopError(
            ErrorCode.NOT_FOUND,
            "this endpoint was removed in single-user mode",
        )

    for prefix in _RETIRED_MULTI_USER_PREFIXES:
        router.add_api_route(prefix, retired_multi_user_endpoint, methods=methods)
        router.add_api_route(f"{prefix}/{{rest:path}}", retired_multi_user_endpoint, methods=methods)

    return router


_NO_CACHE_DASHBOARD_NAMES = frozenset({"sw.js", "manifest.json", "index.html"})


def dashboard_cache_control(full_path: str) -> str | None:
    """Cache-Control for a dashboard SPA path, or ``None`` to leave unset."""
    name = Path(full_path).name.lower() if full_path else "index.html"
    if not full_path or name in _NO_CACHE_DASHBOARD_NAMES:
        return "no-cache"
    # Vite emits content-hashed files under assets/ — safe to pin forever.
    if full_path.startswith("assets/"):
        return "public, max-age=31536000, immutable"
    # monaco-editor's min/vs tree is copied unhashed. Revalidate so an upgrade
    # does not keep an editor.main.js that points at removed worker names.
    if full_path.startswith("monaco/"):
        return "no-cache"
    return None


def default_dashboard_dir() -> Path:
    """Directory holding the built dashboard (``_internal/octop/dashboard`` when frozen)."""
    return Path(__file__).parent.parent / "dashboard"


def _dashboard_response(path: Path, full_path: str) -> FileResponse:
    # ``FileResponse`` opens the file when the response is sent, so a file that
    # is missing by then used to escape as ``FileNotFoundError`` -> 500. A
    # missing static file is a 404, never a server error.
    try:
        path.stat()
    except OSError:
        raise HTTPException(status_code=404, detail="Not Found") from None
    response = FileResponse(path)
    cache_control = dashboard_cache_control(full_path)
    if cache_control is not None:
        response.headers["Cache-Control"] = cache_control
    return response


# A missing file must 404 instead of falling back to ``index.html``: answering
# ``/sw.js`` or ``/favicon.ico`` with HTML makes the browser reject it as a
# worker/script, which hides the real cause (a stale or partial build).
_STATIC_FILE_SUFFIXES = frozenset(
    {
        ".js",
        ".mjs",
        ".cjs",
        ".css",
        ".map",
        ".json",
        ".txt",
        ".xml",
        ".wasm",
        ".html",
        ".ico",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".webm",
        ".mp4",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
    }
)


def looks_like_static_file(full_path: str) -> bool:
    """True when the path names a file (by suffix) rather than an SPA route."""
    return Path(full_path).suffix.lower() in _STATIC_FILE_SUFFIXES


def is_dashboard_asset_path(full_path: str) -> bool:
    """True for build artifacts that must 404 instead of falling back to the SPA.

    ``/assets/*`` are content-hashed scripts. ``/monaco/*`` is the vendored
    editor tree. Returning ``index.html`` for either makes the browser treat
    HTML as a script or worker.
    """
    return full_path.startswith(("assets/", "monaco/"))


def _dashboard_fallback(index_file: Path, full_path: str) -> FileResponse:
    """Serve the SPA shell for routes; 404 for a missing file.

    Answering ``/assets/index.<old-hash>.js`` with ``index.html`` makes the
    browser reject HTML as a module script ("not a valid JavaScript MIME
    type"), which hides the real cause — a stale shell after an upgrade. The
    same applies to any other missing file such as ``/sw.js`` or
    ``/favicon.ico``, so file-like paths must 404 rather than return the shell.
    """
    if is_dashboard_asset_path(full_path) or looks_like_static_file(full_path):
        raise HTTPException(status_code=404, detail="Not Found")
    return _dashboard_response(index_file, "")


def _mount_routers(app: FastAPI, mounts: Sequence[_RouterMount]) -> None:
    for spec in mounts:
        app.include_router(spec.router, prefix=spec.prefix, tags=list(spec.tags))


def _install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(OctopError)
    async def _octop(request: Request, exc: OctopError) -> JSONResponse:
        # Client responses are locale-localized; log the original English message
        # so INTERNAL_ERROR (and other 5xx) remain diagnosable in ~/.octop/logs.
        if exc.status >= 500:
            logger.error(
                "OctopError %s in %s: %s",
                exc.code.value,
                request.url.path,
                exc.message,
                exc_info=exc,
            )
        locale = resolve_request_locale(request)
        return JSONResponse(status_code=exc.status, content=exc.to_envelope(locale=locale))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception in %s", request.url.path)
        locale = resolve_request_locale(request)
        err = OctopError.localized(ErrorCode.INTERNAL_ERROR, locale)
        return JSONResponse(status_code=err.status, content=err.to_envelope())


def build_app(server: OctopServer, *, defer_heavy: bool = False) -> FastAPI:
    """Build the FastAPI app.

    ``defer_heavy=True`` mounts only the routes needed for the first dashboard
    paint; the caller must invoke :func:`mount_deferred_routers` later. Tests and
    other in-process callers keep the historical "everything is mounted" shape.
    """
    cfg = server.services.config if server.services else getattr(server, "config", None)
    enable_dashboard = cfg.enable_dashboard if cfg else True
    enable_api_docs = cfg.enable_api_docs if cfg else False

    app = FastAPI(
        title="HappyClaw API",
        version="0.1.0",
        description=API_DESCRIPTION,
        openapi_url="/api/openapi.json" if enable_api_docs else None,
        openapi_tags=OPENAPI_TAGS,
    )
    configure_openapi(app)
    app.state.octop_server = server
    _install_exception_handlers(app)

    # Optional shared-secret gate for phones / cross-origin dashboards. It is
    # installed *before* CORS so CORSMiddleware wraps its 401 responses —
    # otherwise a browser cannot read the status and reports a network failure.
    from octop.api.middleware.access_token import install as install_access_token

    install_access_token(app, server)

    if cfg and cfg.cors_origins:
        from octop.api.deps import ACCESS_TOKEN_RESPONSE_HEADER

        origins = list(cfg.cors_origins)
        # "*" must not be combined with credentials: browsers reject that pair.
        allow_all = "*" in origins
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"] if allow_all else origins,
            allow_credentials=not allow_all,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[ACCESS_TOKEN_RESPONSE_HEADER],
        )

    # Added after CORS so compression wraps it (middleware added last runs
    # first) and also shrinks the JSON payloads CORS decorates.
    from octop.api.middleware.compression import install as install_compression

    install_compression(app)

    from octop.api.middleware.bridge_proxy import install as install_bridge_proxy

    # Bridge proxy must sit inside the identity middleware so
    # ``request.state.octop_user`` is set (Starlette runs the last-added
    # middleware first).
    install_bridge_proxy(app, server)
    # Single-user mode: no JWT gate, no setup lockdown. The middleware below
    # only attaches the local owner to ``request.state``.
    install_jwt_auth(app, server)

    bind_bridge_asgi(app, server)

    from octop.infra.setup.tls.challenge import challenge_store

    @app.get("/.well-known/acme-challenge/{token}", include_in_schema=False)
    async def acme_http01_challenge(token: str) -> PlainTextResponse:
        body = challenge_store.get(token)
        if body is None:
            raise HTTPException(status_code=404, detail="challenge not found")
        return PlainTextResponse(body)

    # Only the routes the shell needs before the first dashboard paint are
    # mounted here. The remaining routers cost ~20s of module import on slow
    # volumes (langchain, aiohttp, ldap3, docx…), so ``mount_deferred_routers``
    # adds them once the socket is already accepting connections.
    from octop.api.routers import (
        auth,
        auth_device,
        bao,
        health,
        i18n,
        preferences,
        runtime,
        setup,
    )

    _mount_routers(
        app,
        [
            _RouterMount(setup.router, "/api", ["setup"]),
            # Bao is an always-on shell entry; mount it with first paint so the
            # floating button never opens onto a 404.
            _RouterMount(bao.router, "/api/bao", ["agents"]),
            _RouterMount(auth.router, "/api/auth", ["auth"]),
            # The desktop shell exchanges its device credential for a token on
            # cold start, before the deferred batch is mounted.
            _RouterMount(auth_device.router, "/api/auth", ["auth"]),
            _RouterMount(preferences.router, "/api", ["auth"]),
            _RouterMount(i18n.router, "/api", ["i18n"]),
            _RouterMount(health.router, "/api/health", ["health"]),
            _RouterMount(runtime.router, "/api/runtime", ["health"]),
        ],
    )
    if not defer_heavy:
        # Historical shape for tests and in-process callers: everything mounted.
        mount_critical_routers(app)
        mount_deferred_routers(app)

    if enable_api_docs:
        # Documentation-only dependency; importing it pulls the whole openapi
        # model tree, so keep it out of the default (docs disabled) boot path.
        from scalar_fastapi import get_scalar_api_reference  # noqa: PLC0415

        @app.get("/api/docs", include_in_schema=False)
        async def api_docs() -> HTMLResponse:
            return get_scalar_api_reference(
                openapi_url=app.openapi_url,
                title="HappyClaw API",
            )

    if enable_dashboard:
        dashboard_dir = default_dashboard_dir()
        index_file = dashboard_dir / "index.html"
        if index_file.exists():
            @app.get("/sw.js", include_in_schema=False)
            async def service_worker() -> Response:
                """Serve the bundled worker; unregister when the build has none.

                ``npm run build:fast`` disables the PWA plugin, so such a build
                has no ``sw.js`` while the entry still calls ``registerSW()``.
                A stub that unregisters keeps that path from becoming a
                permanent 404/500 in the browser console.
                """
                sw_file = dashboard_dir / "sw.js"
                if sw_file.is_file():
                    return _dashboard_response(sw_file, "sw.js")
                logger.warning(
                    "dashboard 缺少 sw.js（可能是 build:fast 产物），返回注销桩：%s", dashboard_dir
                )
                return Response(
                    content="self.registration.unregister();\n",
                    media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"},
                )

            # Everything mounted after this point must be inserted *before* the
            # SPA catch-all, otherwise Starlette never reaches it.
            app.state.octop_spa_index = len(app.router.routes)

            @app.get("/{full_path:path}", include_in_schema=False)
            async def spa_fallback(full_path: str) -> FileResponse:
                if full_path.startswith(("api/", "ws/")):
                    raise HTTPException(status_code=404, detail="Not Found")

                if full_path:
                    raw_path = Path(full_path)
                    # Reject absolute paths and parent-dir references before
                    # joining, so user input never drives a path expression.
                    if raw_path.is_absolute() or ".." in raw_path.parts:
                        return _dashboard_fallback(index_file, full_path)
                    candidate = (dashboard_dir / Path(*raw_path.parts)).resolve()
                    try:
                        candidate.relative_to(dashboard_dir.resolve())
                    except ValueError:
                        return _dashboard_fallback(index_file, full_path)
                    if candidate.is_file():
                        return _dashboard_response(candidate, full_path)
                return _dashboard_fallback(index_file, full_path)

    return app


def bind_bridge_asgi(app: FastAPI, server: OctopServer) -> None:
    """Attach the bridge peer ASGI app once the runtime exists (no-op before)."""
    runtime = server.app_runtime
    if runtime is None or runtime.bridge_manager is None:
        return
    from octop.api.bridge_peer import prepare_peer_dashboard_turn
    from octop.api.routers.browser.stream import run_browser_stream_session

    runtime.bridge_manager.bind_asgi_app(
        app,
        peer_turn_runner=prepare_peer_dashboard_turn,
        peer_browser_runner=run_browser_stream_session,
    )


def _mount_before_spa(app: FastAPI, specs: Sequence[_RouterMount]) -> None:
    """Mount *specs* ahead of the SPA catch-all, keeping later batches behind.

    ``octop_spa_index`` moves forward with every batch so a second mount does
    not slide the new routes in front of routes that were already usable.
    """
    start = len(app.router.routes)
    _mount_routers(app, specs)
    added = app.router.routes[start:]
    if not added:
        return
    del app.router.routes[start:]
    index = getattr(app.state, "octop_spa_index", None)
    if index is None or index > len(app.router.routes):
        index = len(app.router.routes)
    app.router.routes[index:index] = added
    app.state.octop_spa_index = index + len(added)
    app.openapi_schema = None


def critical_router_specs() -> list[_RouterMount]:
    """Routers without which the first chat turn cannot be served.

    Measured import cost on the slow volume: chat ~0.85s, agents ~0.33s,
    slash ~0.04s. Everything else waits for :func:`deferred_router_specs`.
    """
    from octop.api.routers import agents, chat, slash  # noqa: PLC0415

    return [
        _RouterMount(agents.router, "/api/agents", ["agents"]),
        _RouterMount(chat.router, "/api", ["chat"]),
        _RouterMount(slash.router, "/api", ["slash"]),
    ]


def import_critical_router_modules() -> None:
    """Warm the first-turn routers without touching the app (worker thread)."""
    critical_router_specs()


def mount_critical_routers(app: FastAPI) -> None:
    """Mount agents/chat/slash so a user can send the first message."""
    if getattr(app.state, "octop_critical_mounted", False):
        return
    app.state.octop_critical_mounted = True
    _mount_before_spa(app, critical_router_specs())


def deferred_router_specs() -> list[_RouterMount]:
    """Import and describe every router that is not needed for first paint.

    Kept in the same relative order as the historical single-shot mount list so
    route resolution does not change once the deferred mount happens.
    """
    from octop.api.routers import (  # noqa: PLC0415
        acp,
        admin,
        agent_files,
        agent_mcp,
        agent_tools,
        backup,
        bridge,
        browser,
        channels,
        cloud,
        connectors,
        cron,
        desktop,
        device_link,
        dsh_compat,
        envs,
        experts,
        internal_mcp,
        knowledge_bases,
        mbti,
        media_generation,
        memory,
        memory_portable,
        memory_storage,
        ollama_models,
        onnx_models,
        phone_access,
        plugins,
        proactive_care,
        providers,
        projects,
        search,
        settings,
        skill_packages,
        skills,
        subagents,
        teams,
        terminal,
        text_assist,
        update,
        uploads,
        usage,
        user_groups,
        users,
        voice,
        workspace,
    )
    from octop.api.routers.decision import router as decision_router  # noqa: PLC0415
    from octop.api.routers.filesystem import router as filesystem_router  # noqa: PLC0415
    from octop.infra.control.connector import router as connector_router  # noqa: PLC0415
    from octop.api.routers.observability import router as observability_router  # noqa: PLC0415
    from octop.api.routers.providers import admin_router as admin_providers_router  # noqa: PLC0415
    from octop.api.routers.security import router as security_router  # noqa: PLC0415
    from octop.api.routers.storage_backends import (  # noqa: PLC0415
        admin_router as admin_storage_router,
    )
    from octop.api.routers.storage_backends import (  # noqa: PLC0415
        user_router as storage_backends_user_router,
    )
    from octop.api.routers.tls import router as tls_router  # noqa: PLC0415
    from octop.api.routers.voice import admin_router as admin_voice_router  # noqa: PLC0415

    specs = [
        _RouterMount(_retired_multi_user_router(), "/api", []),
        _RouterMount(user_groups.router, "/api/user-groups", ["users"]),
        _RouterMount(users.router, "/api/users", ["users"]),
        _RouterMount(agent_tools.router, "/api", ["agents"]),
        _RouterMount(acp.router, "/api", ["agents"]),
        _RouterMount(agent_mcp.router, "/api", ["agent-mcp"]),
        _RouterMount(connectors.router, "/api", ["connectors"]),
        _RouterMount(bridge.router, "/api", ["bridge"]),
        _RouterMount(knowledge_bases.router, "/api", ["knowledge"]),
        _RouterMount(internal_mcp.router, "/api", ["internal-mcp"]),
        _RouterMount(channels.router, "/api", ["channels"]),
        _RouterMount(cloud.router, "/api/cloud", ["cloud"]),
        _RouterMount(cron.router, "/api", ["cron"]),
        _RouterMount(settings.router, "/api", ["settings"]),
        _RouterMount(phone_access.router, "/api/phone-access", ["settings"]),
        _RouterMount(decision_router, "/api", ["settings"]),
        _RouterMount(envs.router, "/api", ["envs"]),
        _RouterMount(search.router, "/api", ["search"]),
        _RouterMount(providers.router, "/api/providers", ["providers"]),
        _RouterMount(voice.router, "/api/voice", ["voice"]),
        _RouterMount(admin.router, "/api/admin", ["admin"]),
        # Public single-user prefix. The desktop shell / tray calls
        # ``POST /api/backup/create``; the same router is mounted under
        # ``/api/admin`` below as a compatibility alias.
        _RouterMount(backup.router, "/api", ["backup"]),
        _RouterMount(backup.router, "/api/admin", ["admin"]),
        _RouterMount(admin_providers_router, "/api/admin/providers", ["admin"]),
        _RouterMount(admin_voice_router, "/api/admin/voice/providers", ["admin"]),
        _RouterMount(observability_router, "/api/admin/observability", ["observability"]),
        _RouterMount(media_generation.router, "/api/admin/media-generation", ["providers"]),
        _RouterMount(tls_router, "/api/admin/tls", ["tls"]),
        _RouterMount(security_router, "/api/admin/security", ["security"]),
        _RouterMount(admin_storage_router, "/api/admin/storage-backends", ["admin"]),
        _RouterMount(
            storage_backends_user_router, "/api/storage-backends", ["storage-backends"]
        ),
        _RouterMount(filesystem_router, "/api/filesystem", ["filesystem"]),
        _RouterMount(mbti.router, "/api", ["mbti"]),
        _RouterMount(experts.router, "/api", ["experts"]),
        _RouterMount(projects.router, "/api", ["agents"]),
        _RouterMount(teams.router, "/api", ["teams"]),
        _RouterMount(text_assist.router, "/api", ["text-assist"]),
        _RouterMount(workspace.router, "/api", ["workspace"]),
        _RouterMount(agent_files.router, "/api", ["agent_files"]),
        _RouterMount(memory.router, "/api", ["memory"]),
        _RouterMount(memory_portable.router, "/api", ["memory"]),
        _RouterMount(memory_storage.router, "/api", ["memory"]),
        _RouterMount(proactive_care.router, "/api", ["proactive-care"]),
        _RouterMount(usage.router, "/api", ["usage"]),
        _RouterMount(usage.admin_router, "/api/admin", ["admin"]),
        _RouterMount(skill_packages.router, "/api", ["skill-packages"]),
        _RouterMount(skills.router, "/api", ["skills"]),
        _RouterMount(subagents.router, "/api", ["subagents"]),
        _RouterMount(terminal.router, "/api", ["terminal"]),
        _RouterMount(uploads.router, "/api", ["chat"]),
        _RouterMount(update.router, "/api", ["update"]),
        _RouterMount(browser.router, "/api", ["browser"]),
        _RouterMount(desktop.router, "/api", ["desktop"]),
        # 手机 App 直连（跨局域网 TLS）：服务端地址由用户显式配置，
        # 与已移除的 ADB 手机能力开关无关。
        _RouterMount(device_link.router, "/api", ["device-link"]),
        # 手机端连接器：手机主动拨号进来配对，再由服务端推送消息、接收回复。
        _RouterMount(connector_router.router, "/api", ["connector"]),
        _RouterMount(ollama_models.router, "/api", ["ollama"]),
        _RouterMount(onnx_models.router, "/api", ["onnx"]),
        _RouterMount(plugins.router, "/api", ["plugins"]),
        _RouterMount(dsh_compat.router, "/api/dsh-compat", ["dsh-compat"]),
    ]
    return specs


def import_deferred_router_modules() -> None:
    """Import the deferred routers without touching the app (worker thread)."""
    deferred_router_specs()


def mount_deferred_routers(app: FastAPI) -> None:
    """Mount the remaining routers ahead of the SPA catch-all.

    The heavy import work happens inside :func:`deferred_router_specs`; call this
    from the event loop only after :func:`import_deferred_router_modules` has run
    in a worker thread, so the loop is not blocked for tens of seconds.
    """
    if getattr(app.state, "octop_deferred_mounted", False):
        return
    app.state.octop_deferred_mounted = True
    specs = deferred_router_specs()
    _mount_before_spa(app, specs)
