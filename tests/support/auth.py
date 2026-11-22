"""Auth and bootstrap helpers for HTTP integration tests.

Single-user mode deleted the setup wizard: the local owner exists before the
server starts listening. These helpers keep their historical signatures so the
existing integration suite does not need to change, but they no longer create
accounts or check passwords.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

# Meets ``validate_password_policy`` (letter + digit, length ≥ 8).
TEST_PASSWORD = "TestPass12"


def _server_from_client(client: httpx.AsyncClient) -> Any:
    app = getattr(client, "_octop_app", None)
    return getattr(getattr(app, "state", None), "octop_server", None)


async def wizard_token(client: httpx.AsyncClient, home: Path) -> str:  # noqa: ARG001
    """Deprecated: wizard tokens do not exist; return the placeholder token."""
    return "local-owner"


async def bootstrap_admin(
    client: httpx.AsyncClient,
    home: Path,
    *,
    username: str = "admin",
    password: str = TEST_PASSWORD,
) -> httpx.Response:
    """Single-user bootstrap: create the default ``main`` agent if missing.

    Historically this ran verify-password → initial-admin → finish. The local
    owner is now created at startup, so this only needs to materialise the
    default expert (which most integration tests expect to exist).
    """
    server = _server_from_client(client)
    if server is not None and getattr(server, "services", None) is not None:
        from happyclaw.infra.agents.experts.default_agent import (
            SETUP_DEFAULT_AGENT_ID,
            try_bootstrap_default_agent,
        )

        await try_bootstrap_default_agent(
            server,
            user_id=server.services.owner.owner_id(),
            agent_id=SETUP_DEFAULT_AGENT_ID,
        )
    return httpx.Response(
        status_code=201,
        json={"username": username, "local": True},
        request=httpx.Request("POST", "http://testserver/api/setup/initial-admin"),
    )


async def login(
    client: httpx.AsyncClient,
    *,
    username: str = "admin",
    password: str = TEST_PASSWORD,
) -> str:
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def auth_header(
    client: httpx.AsyncClient,
    *,
    username: str = "admin",
    password: str = TEST_PASSWORD,
) -> dict[str, str]:
    return bearer(await login(client, username=username, password=password))


async def seed_openai_provider(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    *,
    name: str = "openai",
    api_key: str = "k",
) -> None:
    r = await client.post(
        "/api/admin/providers",
        headers=auth,
        json={
            "name": name,
            "kind": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": api_key,
            "models": [
                {
                    "id": "gpt-4o",
                    "name": "GPT-4o",
                    "enabled": True,
                    "input": ["text"],
                    "thinking": False,
                }
            ],
        },
    )
    r.raise_for_status()


async def create_agent(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    *,
    name: str = "bot",
    config: dict[str, Any] | None = None,
) -> str:
    body = {
        "name": name,
        "config": config or {"providers": ["openai"], "default_model": "openai:gpt-4o"},
    }
    r = await client.post("/api/agents", headers=auth, json=body)
    r.raise_for_status()
    data = r.json()
    return data.get("agent_id") or data["id"]


async def create_user(
    client: httpx.AsyncClient,
    admin_auth: dict[str, str],
    *,
    username: str,
    password: str = TEST_PASSWORD,
    role: str = "user",
    permissions: list[str] | None = None,
) -> dict[str, str]:
    """Obsolete in single-user mode: there is no second account.

    Multi-account integration tests still call this helper; skipping at the
    call site keeps them visible as "not applicable" instead of drowning the
    suite in 400s.
    """
    pytest.skip("single-user mode removed multi-account creation")


async def ensure_users(
    client: httpx.AsyncClient,
    admin_auth: dict[str, str],
    *usernames: str,
    password: str = TEST_PASSWORD,
) -> dict[str, dict[str, str]]:
    auths: dict[str, dict[str, str]] = {}
    for username in usernames:
        auths[username] = await create_user(
            client,
            admin_auth,
            username=username,
            password=password,
        )
    return auths


async def resolve_user_id(
    client: httpx.AsyncClient,
    admin_auth: dict[str, str],
    username: str,
) -> int:
    users = (await client.get("/api/users", headers=admin_auth)).json()
    return next(u["id"] for u in users if u["username"] == username)


async def create_provider(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    *,
    name: str = "openai",
    kind: str = "openai",
    api_key: str = "k",
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "kind": kind, "api_key": api_key, **extra}
    r = await client.post("/api/admin/providers", headers=auth, json=body)
    r.raise_for_status()
    return r.json()
