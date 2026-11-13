"""Single-user mode never validates bearer tokens: purpose/version claims are ignored."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.support.app import ensure_control_plane_bound
from tests.support.auth import bootstrap_admin

from octop.api.app import build_app
from octop.api.deps import resolve_user_from_token
from octop.infra.auth.tokens import (
    PURPOSE_ACCESS,
    PURPOSE_MFA,
    PURPOSE_REAUTH,
    sign_token,
)
from octop.infra.server import OctopServer


@pytest.fixture()
async def srv(tmp_path: Path):
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
async def test_mfa_and_reauth_purpose_are_ignored(srv) -> None:
    server, _client = srv
    assert server.services is not None
    owner = server.services.owner.owner()
    secret = server.services.secret_repo.get("jwt")
    assert secret is not None
    mfa = sign_token(
        secret,
        sub=owner.id,
        uname=owner.username,
        role=owner.role,
        purpose=PURPOSE_MFA,
        ttl_seconds=60,
        amr="password",
        mfa_version=0,
    )
    reauth = sign_token(
        secret,
        sub=owner.id,
        uname=owner.username,
        role=owner.role,
        purpose=PURPOSE_REAUTH,
        ttl_seconds=60,
    )
    assert resolve_user_from_token(server, mfa).id == owner.id
    assert resolve_user_from_token(server, reauth).id == owner.id


@pytest.mark.asyncio
async def test_mfa_version_mismatch_is_ignored(srv) -> None:
    server, _client = srv
    assert server.services is not None
    owner = server.services.owner.owner()
    secret = server.services.secret_repo.get("jwt")
    assert secret is not None
    token = sign_token(
        secret,
        sub=owner.id,
        uname=owner.username,
        role=owner.role,
        purpose=PURPOSE_ACCESS,
        mfa_version=0,
    )
    server.services.user_repo.bump_mfa_version(owner.id)
    assert resolve_user_from_token(server, token).id == owner.id


@pytest.mark.asyncio
async def test_password_version_mismatch_is_ignored(srv) -> None:
    server, _client = srv
    assert server.services is not None
    owner = server.services.owner.owner()
    secret = server.services.secret_repo.get("jwt")
    assert secret is not None
    token = sign_token(
        secret,
        sub=owner.id,
        uname=owner.username,
        role=owner.role,
        purpose=PURPOSE_ACCESS,
        password_version=0,
    )
    server.services.user_repo.set_password_hash(owner.id, "rotated-hash")
    assert resolve_user_from_token(server, token).id == owner.id


@pytest.mark.asyncio
async def test_query_access_token_is_ignored(srv) -> None:
    server, client = srv
    assert server.services is not None
    owner = server.services.owner.owner()
    secret = server.services.secret_repo.get("jwt")
    assert secret is not None
    mfa = sign_token(
        secret,
        sub=owner.id,
        uname=owner.username,
        role=owner.role,
        purpose=PURPOSE_MFA,
        ttl_seconds=60,
        amr="password",
    )
    r = await client.get("/api/auth/me", params={"access_token": mfa})
    assert r.status_code == 200
    assert r.json()["username"] == owner.username
