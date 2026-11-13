"""Multi-account role templates are retired.

Single-user mode has no roles to manage, so ``/api/users/roles`` is unmounted.
These tests pin the removal contract: every method answers 404 ``NOT_FOUND``
instead of falling through to ``/api/users/{user_id}`` (422) or the SPA
catch-all (405).
"""

from __future__ import annotations

import pytest

ROLE_PATHS = [
    "/api/users/roles",
    "/api/users/roles/admin",
    "/api/users/roles/admin/avatar",
]


@pytest.fixture
async def client(app_client):
    c, _srv, _home = app_client
    yield c


@pytest.mark.parametrize("path", ROLE_PATHS)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_role_template_routes_are_removed(client, method: str, path: str) -> None:
    r = await client.request(method, path, json={})
    assert r.status_code == 404, f"{method} {path} -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("path", ["/api/users/invites", "/api/users/invites/inv_1"])
async def test_admin_invite_routes_are_removed(client, path: str) -> None:
    for method in ("GET", "POST"):
        r = await client.request(method, path, json={})
        assert r.status_code == 404, f"{method} {path} -> {r.status_code}"
        assert r.json()["error"]["code"] == "NOT_FOUND"


async def test_user_write_routes_stay_mounted_but_read_only(client) -> None:
    """``/api/users`` survives for reads; writes keep the single-user guard."""
    assert (await client.get("/api/users")).status_code == 200
    r = await client.post("/api/users", json={"username": "bob", "password": "x" * 12})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"
