"""Multi-account role templates are retired.

Single-user mode has no roles to manage, so ``/api/users/roles`` is unmounted.
These tests pin the removal contract: every method answers 404 ``NOT_FOUND``
instead of falling through to ``/api/users/{user_id}`` (422) or the SPA
catch-all (405).
"""

from __future__ import annotations

import pytest

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

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


USER_ACCOUNT_PATHS = [
    "/api/users",
    "/api/users/1",
    "/api/users/1/unlock-login",
    "/api/users/1/reset-password",
    "/api/users/1/mfa",
    "/api/user-groups",
    "/api/user-groups/1",
]


@pytest.mark.parametrize("path", USER_ACCOUNT_PATHS)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_user_account_routes_are_removed(client, method: str, path: str) -> None:
    """``/api/users`` and ``/api/user-groups`` CRUD are fully unmounted.

    Only ``GET /api/users/{id}/avatar`` survives (sender portraits in shared
    conversations); its write methods are retired with the rest.
    """
    r = await client.request(method, path, json={})
    assert r.status_code == 404, f"{method} {path} -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_user_avatar_write_methods_are_removed(client, method: str) -> None:
    r = await client.request(method, "/api/users/1/avatar", json={})
    assert r.status_code == 404, f"{method} avatar -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"


async def test_user_avatar_read_survives(client) -> None:
    """Shared conversations render sender portraits: the GET avatar URL works."""
    me = (await client.get("/api/auth/me")).json()
    uploaded = await client.post(
        "/api/auth/me/avatar",
        files={"file": ("avatar.png", _PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    r = await client.get(f"/api/users/{me['id']}/avatar")
    assert r.status_code == 200
    assert r.content == _PNG
