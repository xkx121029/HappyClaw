"""Single-user access tests (replaces the historical JWT middleware suite).

HappyClaw is a single-user local tool: every ``/api/*`` request is served as
the one local owner. These tests pin that contract — no token is required, an
invalid token is ignored, and ``/api/health`` stays anonymous.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.support.app import ensure_control_plane_bound

from happyclaw.api.app import build_app
from happyclaw.api.deps import (
    ACCESS_TOKEN_RESPONSE_HEADER,
    is_jwt_exempt_path,
    is_jwt_exempt_request,
    maybe_sliding_renew_token,
)
from happyclaw.infra.server import OctopServer


def test_every_path_is_exempt_in_single_user_mode() -> None:
    for path in (
        "/api/health",
        "/api/setup/status",
        "/api/auth/me",
        "/api/sessions",
        "/api/tasks",
        "/api/preferences",
        "/api/agents",
        "/api/providers",
    ):
        assert is_jwt_exempt_path(path) is True


def test_is_jwt_exempt_request_always_true() -> None:
    request = httpx.Request("GET", "http://testserver/api/agents")
    assert is_jwt_exempt_request(request) is True  # type: ignore[arg-type]


@pytest.fixture
async def client(tmp_path: Path):
    srv = OctopServer(home=tmp_path)
    await srv.start()
    await ensure_control_plane_bound(srv)
    app = build_app(srv)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c, srv, tmp_path
    await srv.stop()


async def test_health_is_anonymous(client) -> None:
    c, _srv, _home = client
    r = await c.get("/api/health")
    assert r.status_code == 200


async def test_api_without_token_is_served_as_owner(client) -> None:
    c, srv, _home = client
    r = await c.get("/api/agents")
    assert r.status_code == 200
    assert isinstance(r.json(), (list, dict))
    # The request was resolved to the local owner, not rejected.
    assert srv.services is not None
    assert srv.services.owner.owner().username


async def test_invalid_and_expired_tokens_are_ignored(client) -> None:
    c, _srv, _home = client
    for header in ("Bearer not-a-token", "Bearer ", "Basic abc"):
        r = await c.get("/api/agents", headers={"Authorization": header})
        assert r.status_code == 200, header


async def test_auth_me_returns_minimal_local_profile(client) -> None:
    c, _srv, _home = client
    r = await c.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "local"
    assert body["is_local_owner"] is True
    assert "permissions" not in body
    assert not any(key.startswith("sso_") for key in body)


async def test_logout_is_noop(client) -> None:
    c, _srv, _home = client
    r = await c.post("/api/auth/logout")
    assert r.status_code == 204


async def test_setup_status_reports_complete(client) -> None:
    c, _srv, _home = client
    body = (await c.get("/api/setup/status")).json()
    assert body["setup_required"] is False
    assert body["wizard_password_required"] is False
    assert body["single_user"] is True


async def test_login_returns_placeholder_token(client) -> None:
    c, _srv, _home = client
    r = await c.post("/api/auth/login", json={"username": "any", "password": "any"})
    assert r.status_code == 200
    assert r.json()["access_token"] == "local-owner"


async def test_no_sliding_renew_header(client) -> None:
    c, _srv, _home = client
    r = await c.get("/api/auth/me")
    assert r.status_code == 200
    assert ACCESS_TOKEN_RESPONSE_HEADER not in r.headers


async def test_maybe_sliding_renew_is_noop(client) -> None:
    _c, srv, _home = client
    assert maybe_sliding_renew_token(srv, "anything") is None


async def test_api_docs_can_be_opened_without_token(tmp_path: Path) -> None:
    from tests.support.app import write_octop_config

    write_octop_config(tmp_path, enable_api_docs=True)
    srv = OctopServer(home=tmp_path)
    await srv.start()
    await ensure_control_plane_bound(srv)
    app = build_app(srv)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as c:
            assert (await c.get("/api/docs")).status_code == 200
            assert (await c.get("/api/openapi.json")).status_code == 200
    finally:
        await srv.stop()
