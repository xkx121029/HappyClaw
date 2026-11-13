"""LDAP sign-in is retired with multi-account mode.

The ``/api/auth/ldap/*`` router is unmounted; config/status/test all answer 404.
"""

from __future__ import annotations

import pytest

LDAP_PATHS = [
    "/api/auth/ldap/status",
    "/api/auth/ldap/config",
    "/api/auth/ldap/config/test",
]


@pytest.fixture
async def client(app_client):
    c, _srv, _home = app_client
    yield c


@pytest.mark.parametrize("path", LDAP_PATHS)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_ldap_routes_are_removed(client, method: str, path: str) -> None:
    r = await client.request(method, path, json={})
    assert r.status_code == 404, f"{method} {path} -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"
