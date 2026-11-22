"""Single-user login is a no-op; the MFA login surface is retired."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.support.app import ensure_control_plane_bound
from tests.support.auth import TEST_PASSWORD, bootstrap_admin

from happyclaw.api.app import build_app
from happyclaw.infra.auth.mfa.service import MfaService
from happyclaw.infra.errors import ErrorCode, OctopError
from happyclaw.infra.server import OctopServer


@pytest.fixture()
async def env(tmp_path: Path):
    server = OctopServer(home=tmp_path)
    await server.start()
    await ensure_control_plane_bound(server)
    app = build_app(server)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await bootstrap_admin(client, tmp_path)
        yield server, client
    await server.stop()


@pytest.mark.asyncio
async def test_login_returns_local_owner_and_mfa_verify_is_retired(env) -> None:
    """``POST /api/auth/login`` hands back the local owner; MFA endpoints are gone."""
    _server, client = env
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    owner = me.json()

    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": TEST_PASSWORD},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] == "local-owner"
    assert body["token_type"] == "Bearer"
    assert "mfa_required" not in body
    assert body["user"]["username"] == owner["username"]

    vr = await client.post(
        "/api/auth/mfa/verify",
        json={"mfa_token": body["access_token"], "method": "totp", "code": "000000"},
    )
    assert vr.status_code == 404
    assert vr.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_mfa_throttle_does_not_set_login_lock(env) -> None:
    server, _client = env
    assert server.services is not None
    user = server.services.owner.owner()
    row_before = server.services.user_repo.get(user.id)
    assert row_before is not None
    login_locked = row_before.login_locked_until
    for _ in range(5):
        server.services.user_repo.record_mfa_failure(user.id, max_attempts=5, lockout_seconds=900)
    row = server.services.user_repo.get(user.id)
    assert row is not None
    assert row.mfa_locked_until > 0
    assert row.login_locked_until == login_locked


@pytest.mark.asyncio
async def test_recovery_refused_without_verified_factor(env) -> None:
    server, _client = env
    assert server.services is not None
    user = server.services.owner.owner()
    mfa = MfaService(server.services)
    assert not mfa.has_verified_factor(user.id)
    with pytest.raises(OctopError) as ei:
        mfa.recovery_regenerate(user, reauth_token="not-a-token")
    assert ei.value.code in {ErrorCode.MFA_REAUTH_REQUIRED, ErrorCode.MFA_INVALID}
