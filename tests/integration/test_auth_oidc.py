"""OIDC single sign-on is retired with multi-account mode.

The whole ``/api/auth/oidc/*`` surface is unmounted, including the browser
redirect ``GET /callback`` that used to mint tokens.
"""

from __future__ import annotations

import pytest

OIDC_PATHS = [
    "/api/auth/oidc/status",
    "/api/auth/oidc/start",
    "/api/auth/oidc/callback",
    "/api/auth/oidc/exchange",
    "/api/auth/oidc/config",
    "/api/auth/oidc/config/test",
]


@pytest.fixture
async def client(app_client):
    c, _srv, _home = app_client
    yield c


@pytest.mark.parametrize("path", OIDC_PATHS)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_oidc_routes_are_removed(client, method: str, path: str) -> None:
    r = await client.request(method, path, params={"code": "x", "state": "y"}, json={})
    assert r.status_code == 404, f"{method} {path} -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert "access_token" not in r.text
