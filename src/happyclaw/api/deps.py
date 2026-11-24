"""FastAPI dependencies for the single-user local runtime.

HappyClaw no longer has login, sessions or roles: every request on this machine
is served as the one local owner. The historical dependency names are kept so
the ~600 router call sites (``Depends(current_user)`` / ``require_permission``)
and the dashboard contract keep working unchanged.

Token helpers below are kept as deprecated shims for older callers and tests;
they never authenticate anything.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from fastapi import Depends, Header, Query, Request

from happyclaw.infra.auth.tokens import sign_token
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.users.permissions import PERMISSIONS

if TYPE_CHECKING:
    from happyclaw.infra.server import HappyclawServer
    from happyclaw.infra.users.identity import User
else:
    from happyclaw.infra.users.identity import User

# Kept for CORS ``expose_headers`` and legacy clients. Single-user mode never
# issues or renews tokens.
ACCESS_TOKEN_RESPONSE_HEADER = "X-Octop-Access-Token"


def is_jwt_exempt_path(path: str) -> bool:  # noqa: ARG001
    """Deprecated: there is no JWT gate, so every path is exempt."""
    return True


def is_jwt_exempt_request(request: Request) -> bool:  # noqa: ARG001
    """Deprecated: there is no JWT gate, so every request is exempt."""
    return True


def get_server(request: Request) -> HappyclawServer:
    server: HappyclawServer = request.app.state.octop_server
    if not getattr(server, "_started", False):
        raise HappyclawError(ErrorCode.INTERNAL_ERROR, "server not started")
    return server


def require_database(server: HappyclawServer) -> None:
    """Raise when the control-plane DB is not bound (should not happen anymore)."""
    if not server.database_bound:
        raise HappyclawError(
            ErrorCode.SINGLE_USER_INIT_FAILED,
            "control-plane database is not available",
            status=503,
        )


def _owner(server: HappyclawServer) -> User:
    if server.services is None or not server.database_bound:
        raise HappyclawError(
            ErrorCode.SINGLE_USER_INIT_FAILED,
            "control-plane database is not available",
            status=503,
        )
    return server.services.owner.owner()


# ---------------------------------------------------------------------------
# Deprecated token shims (no authentication in single-user mode)
# ---------------------------------------------------------------------------
def extract_raw_token(
    *,
    authorization: str | None = None,
    access_token: str | None = None,
) -> str | None:
    """Deprecated: parse a bearer token header, without validating it."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if access_token:
        return access_token
    return None


def resolve_user_from_token(server: HappyclawServer, token: str | None = None) -> User:  # noqa: ARG001
    """Deprecated: always returns the local owner."""
    return _owner(server)


def maybe_sliding_renew_token(
    server: HappyclawServer, token: str | None = None, user: User | None = None
) -> str | None:  # noqa: ARG001
    """Deprecated: single-user mode never issues tokens."""
    return None


def authenticate_request(request: Request, server: HappyclawServer) -> User:  # noqa: ARG001
    """Deprecated: every local request is the owner."""
    return _owner(server)


_SINGLE_USER_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def single_user_read_only(request: Request) -> None:
    """Router-level guard: account/SSO management is read-only in single-user mode."""
    if request.method in _SINGLE_USER_WRITE_METHODS:
        raise HappyclawError(
            ErrorCode.SINGLE_USER_UNSUPPORTED,
            "single-user mode does not support account management",
        )


# ---------------------------------------------------------------------------
# FastAPI dependencies (names unchanged for all existing routers)
# ---------------------------------------------------------------------------
async def current_user(
    request: Request,
    server: HappyclawServer = Depends(get_server),
    authorization: str | None = Header(None),
    access_token: str | None = Query(None),
) -> User:
    """Return the local owner; headers/query params are ignored."""
    cached = getattr(request.state, "octop_user", None)
    if cached is not None:
        return cast("User", cached)
    user = _owner(server)
    request.state.octop_user = user
    return user


def _deprecated_owner_dependency(server: HappyclawServer = Depends(get_server)) -> User:
    return _owner(server)


def require_permission(key: str) -> Callable[..., Awaitable[User]]:
    """Keep the factory contract, but permissions are not enforced in single-user mode."""
    if key not in PERMISSIONS:
        raise RuntimeError(f"unknown permission key: {key}")

    async def _dep(user: User = Depends(current_user)) -> User:
        return user

    return _dep


def require_any_permission(*keys: str) -> Callable[..., Awaitable[User]]:
    """Keep the factory contract; any key is accepted for validation only."""
    for key in keys:
        if key not in PERMISSIONS:
            raise RuntimeError(f"unknown permission key: {key}")

    async def _dep(user: User = Depends(current_user)) -> User:
        return user

    return _dep


def require_admin() -> Callable[..., Awaitable[User]]:
    """The local owner is the admin; no role check remains."""

    async def _dep(user: User = Depends(current_user)) -> User:
        return user

    return _dep


__all__ = [
    "ACCESS_TOKEN_RESPONSE_HEADER",
    "authenticate_request",
    "current_user",
    "extract_raw_token",
    "get_server",
    "is_jwt_exempt_path",
    "is_jwt_exempt_request",
    "maybe_sliding_renew_token",
    "require_admin",
    "require_any_permission",
    "require_database",
    "require_permission",
    "resolve_user_from_token",
    "sign_token",
    "single_user_read_only",
]
