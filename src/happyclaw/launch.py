"""Composition root — wire OctopServer, FastAPI, and uvicorn for ``octop run``."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from contextlib import suppress
from typing import Any

from happyclaw.infra.desktop import desktop_shell_enabled
from happyclaw.infra.server import OctopServer
from happyclaw.infra.utils.accept_errors import coalesce_accept_errors

logger = logging.getLogger(__name__)

# uvicorn's default ping_timeout is 20s. A busy peer — demo.octop.chat runs
# dozens of agents on one event loop — often reads the pong later than that
# and then closes the socket with 1011 "keepalive ping timeout". The dialer
# redials at once, so cloud collab looks like it is flapping. Keep sending
# pings; do not drop the connection on a late pong. BridgeSession's
# application heartbeat still detects a half-open link.
_WS_PING_INTERVAL = 20.0
_WS_PING_TIMEOUT: float | None = None


def _ensure_linux_bubblewrap() -> None:
    """Best-effort startup provisioning; never fail the ``octop run`` process."""
    try:
        from happyclaw.infra.utils.bwrap import ensure_bubblewrap

        result = ensure_bubblewrap()
    except Exception:
        logger.warning("background bubblewrap provisioning failed", exc_info=True)
        return
    status = result.get("status")
    detail = result.get("detail")
    if status == "degraded":
        logger.warning("background bubblewrap provisioning degraded: %s", detail or "unknown")
    else:
        logger.info("background bubblewrap provisioning status=%s", status)


def _schedule_linux_bubblewrap_ensure() -> asyncio.Task[None] | None:
    """Run bubblewrap provisioning once in the background on Linux."""
    if not sys.platform.startswith("linux"):
        return None
    return asyncio.create_task(
        asyncio.to_thread(_ensure_linux_bubblewrap),
        name="ensure-linux-bubblewrap",
    )


async def _cancel_background_task(task: asyncio.Task[None] | None) -> None:
    """Drop a startup background task on shutdown; never raise."""
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _serve(server: Any) -> None:
    await server.serve()


async def _post_listen_boot(server: Any, app: Any, holder: dict[str, Any]) -> None:
    """Make the first chat turn possible, then load everything else in the back.

    Split on purpose: ``agents`` + ``chat`` is all a turn needs, while the other
    ~58 routers (``agent_files`` alone costs 13.7s, ``agent_tools`` 9.1s,
    ``agent_mcp`` 7.8s, ``acp`` 3.7s) are only needed when the user opens those
    panels. They keep loading after :func:`_post_listen_rest` is spawned, so the
    dashboard can open the conversation much earlier. Never raises.
    """
    from happyclaw.api.app import (
        bind_bridge_asgi,
        import_critical_router_modules,
        mount_critical_routers,
    )
    from happyclaw.infra.utils import startup_timing as timing

    started = time.perf_counter()
    try:
        with timing.segment("post_listen.imports_critical"):
            await asyncio.to_thread(import_critical_router_modules)

        with timing.segment("post_listen.agents"):
            await server.start_runtime()

        with timing.segment("post_listen.routers_critical"):
            mount_critical_routers(app)
            bind_bridge_asgi(app, server)
        timing.emit(
            "chat_ready",
            (time.perf_counter() - started) * 1000.0,
            since_process_ms=round(timing.since_process_ms(), 1),
        )
        holder["rest_task"] = asyncio.create_task(
            _post_listen_rest(server, app, holder), name="post-listen-rest"
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # pragma: no cover - boot must survive auxiliary failures
        logger.exception("post-listen boot failed (non-fatal)")


async def _post_listen_rest(server: Any, app: Any, holder: dict[str, Any]) -> None:
    """Load the panels that are not needed to send a message.

    Runs after ``chat_ready``; memory control is up first (2.5s) so the local CLI
    can drive the agent, then the remaining routers are imported and mounted.
    """
    from happyclaw.api.app import import_deferred_router_modules, mount_deferred_routers
    from happyclaw.infra.utils import startup_timing as timing

    started = time.perf_counter()
    try:
        from happyclaw.infra.agents.memory.slim_control import MemorySlimControl

        with timing.segment("listen.memory_control"):
            memory_control = MemorySlimControl(server)
            await memory_control.start()
            holder["memory_control"] = memory_control

        with timing.segment("post_listen.imports"):
            await asyncio.to_thread(import_deferred_router_modules)

        with timing.segment("post_listen.routers"):
            mount_deferred_routers(app)
        timing.emit(
            "post_listen",
            (time.perf_counter() - started) * 1000.0,
            since_process_ms=round(timing.since_process_ms(), 1),
        )
    except asyncio.CancelledError:
        raise
    except Exception:  # pragma: no cover - boot must survive auxiliary failures
        logger.exception("post-listen rest failed (non-fatal)")


async def run_foreground(
    *,
    host: str | None,
    port: int | None,
    reload: bool,
    workers: int,
    log_level: str | None,
    ssl_certfile: str | None,
    ssl_keyfile: str | None,
) -> None:
    """Boot the domain server, serve the HTTP API, then shut down cleanly."""
    import uvicorn

    from happyclaw.api.app import build_app
    from happyclaw.infra.bridge.transport import BRIDGE_WS_MAX_BYTES
    from happyclaw.infra.setup.tls.http_companion import build_http_companion_app
    from happyclaw.infra.setup.tls.listeners import build_listen_plan
    from happyclaw.infra.setup.tls.store import resolve_tls_paths

    srv = OctopServer()
    await srv.start(boot_runtime=False)
    from happyclaw.infra.utils import startup_timing as _timing

    _timing.mark("listen.begin")
    bwrap_task = _schedule_linux_bubblewrap_ensure()
    # Greenfield deferral leaves services unset until /setup/database binds.
    cfg = srv.services.config if srv.services is not None else srv.config
    assert cfg is not None
    bind_host = host or cfg.bind_host
    bind_port = port or cfg.port
    if desktop_shell_enabled():
        # Desktop-hosted sidecar always serves one loopback HTTP listener; it
        # must ignore any persisted TLS / dual-port configuration.
        ssl_certfile = None
        ssl_keyfile = None
    elif ssl_certfile is None and ssl_keyfile is None:
        ssl_certfile, ssl_keyfile = resolve_tls_paths(srv.paths.root, cfg.tls)

    plan = build_listen_plan(
        cfg,
        bind_host=bind_host,
        bind_port=bind_port,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )
    level = (log_level or cfg.log_level).lower()
    worker_count = 1 if plan.dual_listeners or reload else workers
    if plan.dual_listeners and (reload or workers > 1):
        logger.warning(
            "TLS dual-port mode forces workers=1 and disables reload",
        )
        reload = False

    app = build_app(srv, defer_heavy=True)
    _timing.emit("listen.build_app", _timing.since_mark_ms("listen.begin") or 0.0)
    _timing.mark("listen.bind")
    servers: list[uvicorn.Server] = []
    listen_logged = [False]

    class _TimedServer(uvicorn.Server):
        """Records the moment the socket accepts traffic (the real "usable")."""

        async def startup(self, sockets: Any = None) -> None:
            await super().startup(sockets=sockets)
            if listen_logged[0]:
                return
            listen_logged[0] = True
            listen_ms = _timing.since_mark_ms("listen.begin")
            bind_ms = _timing.since_mark_ms("listen.bind")
            _timing.emit(
                "listen",
                listen_ms if listen_ms is not None else 0.0,
                bind_ms=None if bind_ms is None else round(bind_ms, 1),
                since_process_ms=round(_timing.since_process_ms(), 1),
            )

    if plan.dual_listeners:
        assert plan.https_port is not None
        assert plan.http_port is not None
        https_config = uvicorn.Config(
            app,
            host=plan.bind_host,
            port=plan.https_port,
            log_level=level,
            workers=worker_count,
            reload=False,
            ssl_certfile=plan.ssl_certfile,
            ssl_keyfile=plan.ssl_keyfile,
            ws_max_size=BRIDGE_WS_MAX_BYTES,
            ws_ping_interval=_WS_PING_INTERVAL,
            ws_ping_timeout=_WS_PING_TIMEOUT,
        )
        companion = build_http_companion_app(https_port=plan.https_port)
        http_config = uvicorn.Config(
            companion,
            host=plan.bind_host,
            port=plan.http_port,
            log_level=level,
            workers=1,
            reload=False,
        )
        servers.append(_TimedServer(https_config))
        servers.append(_TimedServer(http_config))
        logger.info(
            "Listening on https://%s:%s and http://%s:%s (ACME + redirect)",
            plan.bind_host,
            plan.https_port,
            plan.bind_host,
            plan.http_port,
        )
    else:
        single_config = uvicorn.Config(
            app,
            host=plan.bind_host,
            port=plan.http_port or bind_port,
            log_level=level,
            workers=worker_count,
            reload=reload,
            ssl_certfile=plan.ssl_certfile,
            ssl_keyfile=plan.ssl_keyfile,
            ws_max_size=BRIDGE_WS_MAX_BYTES,
            ws_ping_interval=_WS_PING_INTERVAL,
            ws_ping_timeout=_WS_PING_TIMEOUT,
        )
        servers.append(_TimedServer(single_config))

    from happyclaw.infra.utils import startup_timing as _timing

    memory_control_holder: dict[str, Any] = {}
    with coalesce_accept_errors(asyncio.get_running_loop()):
        # The listener accepts connections as soon as ``serve()`` starts; the
        # agent stack and the remaining routers are loaded afterwards so
        # ``/api/health`` — and therefore the desktop splash — does not wait.
        post_boot = asyncio.create_task(
            _post_listen_boot(srv, app, memory_control_holder),
            name="post-listen-boot",
        )
        try:
            await asyncio.gather(*(_serve(s) for s in servers))
        finally:
            await _cancel_background_task(post_boot)
            rest_task = memory_control_holder.get("rest_task")
            if rest_task is not None:
                await _cancel_background_task(rest_task)
            memory_control = memory_control_holder.get("memory_control")
            if memory_control is not None:
                await memory_control.close()
            await _cancel_background_task(bwrap_task)
            await srv.stop()


def run_foreground_blocking(**kwargs: Any) -> None:
    """Sync entry for Click commands and tests."""
    asyncio.run(run_foreground(**kwargs))
