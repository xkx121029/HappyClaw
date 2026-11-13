"""Invite-based signup is retired with multi-account mode.

Both the public redeem/validate endpoints and the admin invite list are
unmounted; the paths must answer 404 rather than 400/405/422.
"""

from __future__ import annotations

import pytest

INVITE_PATHS = [
    "/api/auth/invite/validate",
    "/api/auth/invite/redeem",
    "/api/users/invites",
    "/api/users/invites/inv_1",
    "/api/users/invites/inv_1/revoke",
]


@pytest.fixture
async def client(app_client):
    c, _srv, _home = app_client
    yield c


@pytest.mark.parametrize("path", INVITE_PATHS)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_invite_routes_are_removed(client, method: str, path: str) -> None:
    r = await client.request(method, path, json={"token": "x"})
    assert r.status_code == 404, f"{method} {path} -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"
