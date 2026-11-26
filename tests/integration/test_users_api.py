"""``/api/users`` and ``/api/user-groups`` are fully unmounted in single-user mode.

The historical read-only CRUD contract is gone: every account-management
surface answers ``404 NOT_FOUND`` on every method. Only
``GET /api/users/{id}/avatar`` survives (sender portraits in shared
conversations); profile edits go through ``/api/auth/me``.
"""

from __future__ import annotations

import pytest

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

RETIRED_PATHS = [
    "/api/users",
    "/api/users/1",
    "/api/users/1/unlock-login",
    "/api/users/1/reset-password",
    "/api/users/1/mfa",
    "/api/users/batch",
    "/api/user-groups",
    "/api/user-groups/1",
    "/api/user-groups/audience",
]


@pytest.mark.parametrize("path", RETIRED_PATHS)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_user_account_routes_are_removed(env, method: str, path: str) -> None:
    c, _srv, _auth = env
    r = await c.request(method, path, json={})
    assert r.status_code == 404, f"{method} {path} -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_user_avatar_write_methods_are_removed(env, method: str) -> None:
    c, _srv, _auth = env
    r = await c.request(method, "/api/users/1/avatar", json={})
    assert r.status_code == 404, f"{method} avatar -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"


async def test_user_avatar_read_survives(env) -> None:
    """Shared conversations render sender portraits: the GET avatar URL works."""
    c, _srv, auth = env
    me = (await c.get("/api/auth/me", headers=auth)).json()
    uploaded = await c.post(
        "/api/auth/me/avatar",
        headers=auth,
        files={"file": ("avatar.png", _PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    r = await c.get(f"/api/users/{me['id']}/avatar", headers=auth)
    assert r.status_code == 200
    assert r.content == _PNG


async def test_owner_profile_edits_go_through_auth_me(env) -> None:
    """Account editing is retired; the owner profile is edited via /auth/me."""
    c, _srv, auth = env
    me = (await c.get("/api/auth/me", headers=auth)).json()
    r = await c.patch("/api/auth/me", headers=auth, json={"display_name": "Root"})
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Root"
    assert r.json()["id"] == me["id"]
