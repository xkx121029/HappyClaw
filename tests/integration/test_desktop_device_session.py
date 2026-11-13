"""Desktop shell device-session contract in single-user mode.

The shell still calls ``/api/auth/device/*`` on boot, but there is no session
layer anymore: register is a no-op, token always returns the local placeholder,
and revoke is a 204. Nothing here authenticates or creates accounts.
"""

from __future__ import annotations

import pytest

DEVICE = "device-token-abc"
LOCAL_TOKEN = "local-owner"


@pytest.fixture
async def client(app_client):
    c, _srv, _home = app_client
    yield c


async def test_register_is_a_noop(client) -> None:
    me = (await client.get("/api/auth/me")).json()
    r = await client.post(
        "/api/auth/device/register",
        json={"device_token": DEVICE, "label": "desktop"},
    )
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["ok"] is True
    assert body["username"] == me["username"]
    assert "set-cookie" not in {k.lower() for k in r.headers}


async def test_token_returns_local_owner_without_checking_credential(client) -> None:
    me = (await client.get("/api/auth/me")).json()
    r = await client.post("/api/auth/device/token", json={"device_token": "garbage"})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["access_token"] == LOCAL_TOKEN
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 0
    assert body["user"]["username"] == me["username"]


async def test_token_is_stable_across_calls(client) -> None:
    first = (await client.post("/api/auth/device/token", json={"device_token": DEVICE})).json()
    second = (await client.post("/api/auth/device/token", json={"device_token": DEVICE})).json()
    assert first["access_token"] == second["access_token"] == LOCAL_TOKEN


async def test_revoke_returns_no_content(client) -> None:
    r = await client.post("/api/auth/device/revoke", json={"device_token": DEVICE})
    assert r.status_code == 204
    assert r.content == b""


async def test_device_calls_do_not_create_accounts(client) -> None:
    before = {row["username"] for row in (await client.get("/api/users")).json()}
    await client.post("/api/auth/device/register", json={"device_token": DEVICE})
    await client.post("/api/auth/device/token", json={"device_token": DEVICE})
    await client.post("/api/auth/device/revoke", json={"device_token": DEVICE})
    after = {row["username"] for row in (await client.get("/api/users")).json()}
    assert after == before


async def test_register_requires_device_token(client) -> None:
    r = await client.post("/api/auth/device/register", json={"device_token": ""})
    assert r.status_code == 422
