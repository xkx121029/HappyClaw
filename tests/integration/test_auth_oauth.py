"""OAuth broker sign-in is retired with multi-account mode.

``/api/auth/oauth/*`` is unmounted, including bind/unbind and the browser
redirect ``GET /callback``.
"""

from __future__ import annotations

import pytest

OAUTH_PATHS = [
    "/api/auth/oauth/status",
    "/api/auth/oauth/start",
    "/api/auth/oauth/callback",
    "/api/auth/oauth/exchange",
    "/api/auth/oauth/bind/start",
    "/api/auth/oauth/unbind",
    "/api/auth/oauth/providers/github",
    "/api/auth/oauth/providers/github/test",
]


@pytest.fixture
async def client(app_client):
    c, _srv, _home = app_client
    yield c


@pytest.mark.parametrize("path", OAUTH_PATHS)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_oauth_routes_are_removed(client, method: str, path: str) -> None:
    r = await client.request(method, path, params={"code": "x", "state": "y"}, json={})
    assert r.status_code == 404, f"{method} {path} -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert "access_token" not in r.text
