"""Attach the local owner to ``request.state`` for every ``/api/*`` request.

Single-user mode has no authentication gate: no token is read, validated or
renewed. The middleware only pre-populates ``request.state.octop_user`` so
route dependencies and the bridge proxy can reuse one resolution per request.

Resolution is best-effort: when the control-plane DB is still booting (for
example ``/api/health`` during startup) the state is left unset and the request
is allowed through.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request

_INSTALL_ATTR = "_octop_jwt_auth_installed"
logger = logging.getLogger(__name__)


def install(app: Any, server: Any) -> None:
    if getattr(app, _INSTALL_ATTR, False):
        return
    setattr(app, _INSTALL_ATTR, True)

    @app.middleware("http")  # type: ignore[untyped-decorator]
    async def _local_owner_identity(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        if request.url.path.startswith("/api/"):
            try:
                request.state.octop_user = server.services.owner.owner()
            except Exception:
                # Startup, migrations and /api/health must never be blocked by
                # identity resolution; route-level deps raise if they need it.
                logger.debug(
                    "local owner not resolvable yet for %s", request.url.path, exc_info=True
                )
        return await call_next(request)
