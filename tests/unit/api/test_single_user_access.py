"""Single-user delivery path: no token, no setup wizard, no account management.

These tests pin the contract the dashboard/desktop depend on. Every request is
anonymous on the local machine and must never answer ``401`` or
``setup_required=true``.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.support.app import ensure_control_plane_bound

from happyclaw.api.app import build_app
from happyclaw.infra.server import HappyclawServer


@pytest.fixture
async def client(tmp_path: Path):
    srv = HappyclawServer(home=tmp_path)
    await srv.start()
    await ensure_control_plane_bound(srv)
    app = build_app(srv)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c, srv
    await srv.stop()


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/setup/status",
        "/api/preferences",
        "/api/agents",
        "/api/providers",
        "/api/runtime/activity",
        "/api/teams",
        "/api/user-groups/audience",
        "/api/users",
    ],
)
async def test_anonymous_get_is_served(client, path: str) -> None:
    c, _srv = client
    r = await c.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"


async def test_setup_status_is_complete(client) -> None:
    c, _srv = client
    body = (await c.get("/api/setup/status")).json()
    assert body["setup_required"] is False
    assert body["wizard_password_required"] is False
    assert body["local_account"] is True
    assert body["single_user"] is True
    assert body["database_bound"] is True
    # No wizard on disk in single-user mode: the path field must be gone too.
    assert "wizard_password_path" not in body


async def test_setup_writes_are_rejected_in_chinese(client) -> None:
    c, _srv = client
    for path, payload in (
        ("/api/setup/begin", {}),
        ("/api/setup/verify-password", {"password": "x"}),
        ("/api/setup/initial-admin", {"username": "a", "password": "TestPass12"}),
        ("/api/setup/finish", {}),
        ("/api/setup/database", {"driver": "sqlite"}),
    ):
        r = await c.post(path, json=payload)
        assert r.status_code == 400, path
        err = r.json()["error"]
        assert err["code"] == "SINGLE_USER_UNSUPPORTED"
        assert "单人" in err["message"]


async def test_fresh_instance_has_no_teams_and_no_audience(client) -> None:
    c, _srv = client
    # Expert teams are a single-user feature; a fresh home simply has none.
    assert (await c.get("/api/teams")).json() == []
    assert (await c.get("/api/user-groups/audience")).json() == []


async def test_users_list_only_contains_owner(client) -> None:
    c, srv = client
    users = (await c.get("/api/users")).json()
    assert srv.services is not None
    owner = srv.services.owner.owner()
    assert [u["id"] for u in users] == [owner.id]


async def test_user_creation_is_read_only(client) -> None:
    c, _srv = client
    r = await c.post(
        "/api/users",
        json={"username": "bob", "password": "TestPass12", "role": "user"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"


async def test_runtime_activity_shape(client) -> None:
    c, _srv = client
    body = (await c.get("/api/runtime/activity")).json()
    assert set(body) == {
        "busy",
        "counts",
        "active_turns",
        "dashboard_connections",
        "threads_with_subscribers",
        "terminal_sessions",
        "running_agents",
        "running_jobs",
        "updated_at",
    }
    assert body["busy"] is False
    # ``agent_turn`` / ``terminal`` are always present so the renderer can read
    # ``counts.agent_turn`` without an undefined check.
    assert body["counts"] == {"agent_turn": 0, "terminal": 0}
    assert body["busy"] == (sum(body["counts"].values()) > 0)


async def test_providers_never_return_raw_api_key(client, tmp_path: Path) -> None:
    c, srv = client
    assert srv.services is not None
    srv.services.provider_repo.create(
        name="leaky",
        kind="openai",
        base_url="https://api.openai.com/v1",
        api_key="sk-super-secret-1234",
        extra_json=None,
        models_json=None,
        note=None,
    )
    rows = (await c.get("/api/providers")).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["api_key"] == "****1234"
    assert row["api_key_set"] is True
    assert "sk-super-secret" not in str(row)


async def test_provider_patch_ignores_masked_key(client) -> None:
    """PATCH with a masked key must keep the stored key byte-for-byte identical."""
    import sqlite3

    c, srv = client
    assert srv.services is not None
    original = "sk-real-key-9999"
    pid = srv.services.provider_repo.create(
        name="keep",
        kind="openai",
        base_url="https://api.openai.com/v1",
        api_key=original,
        extra_json=None,
        models_json=None,
        note=None,
    )
    r = await c.patch(
        f"/api/admin/providers/{pid}",
        json={"api_key": "****9999"},
    )
    assert r.status_code == 200

    # Row as stored on disk: ciphertext, never the plaintext key.
    with sqlite3.connect(f"file:{srv.paths.db}?mode=ro", uri=True) as conn:
        raw = conn.execute("SELECT api_key FROM providers WHERE id = ?", (pid,)).fetchone()
    assert raw is not None
    assert raw[0] != original
    assert original not in raw[0]

    # Decrypted through the sealed repo: byte-for-byte equal to the original.
    stored = srv.services.provider_repo.get(pid)
    assert stored is not None
    assert stored.api_key == original
    assert stored.api_key.encode("utf-8") == original.encode("utf-8")


async def test_agent_payload_has_no_user_scope_fields(client) -> None:
    c, _srv = client
    rows = (await c.get("/api/agents")).json()
    assert rows == [] or isinstance(rows, list)
    for row in rows:
        for key in ("user_id", "visibility", "group_ids"):
            assert key not in row


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/oidc/callback?code=abc&state=xyz",
        "/api/auth/oauth/callback?code=abc&state=xyz",
    ],
)
async def test_sso_callbacks_cannot_complete_login(client, path: str) -> None:
    """Browser-redirect callbacks are unmounted, so they cannot mint a session."""
    c, _srv = client
    r = await c.get(path, follow_redirects=False)
    assert r.status_code == 404, f"{path} -> {r.status_code} {r.text[:200]}"
    err = r.json()["error"]
    assert err["code"] == "NOT_FOUND"
    # No JWT is minted and no SSO state cookie is issued.
    assert "access_token" not in r.text
    assert "set-cookie" not in {k.lower() for k in r.headers}


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/mfa/status",
        "/api/auth/mfa/verify",
        "/api/auth/mfa/totp/begin",
        "/api/auth/passkey/status",
        "/api/auth/passkey/login/options",
    ],
)
async def test_mfa_and_passkey_routes_are_removed(client, path: str) -> None:
    """Second factors are unmounted in single-user mode."""
    c, _srv = client
    r = await c.get(path)
    if r.status_code == 405:
        r = await c.post(path, json={})
    assert r.status_code == 404, f"{path} -> {r.status_code} {r.text[:200]}"
    assert r.json()["error"]["code"] == "NOT_FOUND"
