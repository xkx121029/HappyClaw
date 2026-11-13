"""Integration tests for the retired 4-step setup wizard.

Single-user mode deleted the wizard: a clean ``OCTOP_HOME`` binds the default
SQLite control plane at boot and the local owner is created automatically. The
historical routes stay mounted so an older dashboard/desktop build gets a clear
Chinese refusal (``SINGLE_USER_UNSUPPORTED``, HTTP 400) instead of a 404. These
tests pin that retirement contract; the cases keep their historical names where
the covered endpoint still exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from octop.infra.setup.password_file import WIZARD_FILE_NAME, read_password
from tests.support.app import octop_client, write_octop_config

RETIRED_CODE = "SINGLE_USER_UNSUPPORTED"


async def _assert_retired(response: Any) -> None:
    assert response.status_code == 400
    assert response.json()["error"]["code"] == RETIRED_CODE


# ─── verify-password ────────────────────────────────────────────────


async def test_verify_password_returns_token_on_match(env: Any) -> None:
    """The route is retired: no token is ever minted, whatever the password."""
    c, srv, _auth = env
    home = srv.paths.root
    assert read_password(home) is None
    r = await c.post("/api/setup/verify-password", json={"password": "anything"})
    await _assert_retired(r)
    assert "wizard_token" not in r.json()


async def test_verify_password_rejects_mismatch(env: Any) -> None:
    c, _srv, _home = env
    await _assert_retired(await c.post("/api/setup/verify-password", json={"password": "wrong"}))


async def test_verify_password_rate_limited(env: Any) -> None:
    """No verification happens, so no lockout counter exists either."""
    c, _srv, _home = env
    for _ in range(5):
        await _assert_retired(await c.post("/api/setup/verify-password", json={"password": "x"}))
    await _assert_retired(await c.post("/api/setup/verify-password", json={"password": "x"}))


# ─── initial-admin token guard ──────────────────────────────────────


async def test_initial_admin_requires_wizard_token(env: Any) -> None:
    c, _srv, _home = env
    await _assert_retired(
        await c.post(
            "/api/setup/initial-admin",
            json={"username": "admin", "password": "TestPass12"},
        )
    )


async def test_initial_admin_succeeds_with_token(env: Any) -> None:
    """Even with a bearer header the route refuses: the local owner already exists."""
    c, _srv, _home = env
    await _assert_retired(
        await c.post(
            "/api/setup/initial-admin",
            json={"username": "admin", "password": "TestPass12"},
            headers={"Authorization": "Bearer local-owner"},
        )
    )


async def test_initial_admin_rejects_weak_password(env: Any) -> None:
    c, _srv, _home = env
    await _assert_retired(
        await c.post(
            "/api/setup/initial-admin",
            json={"username": "admin", "password": "pw"},
            headers={"Authorization": "Bearer local-owner"},
        )
    )


async def test_initial_admin_requires_password_while_the_gate_is_on(env: Any) -> None:
    c, _srv, _home = env
    await _assert_retired(
        await c.post(
            "/api/setup/initial-admin",
            json={"username": "admin"},
            headers={"Authorization": "Bearer local-owner"},
        )
    )


async def test_initial_admin_without_password_when_the_gate_is_off(
    tmp_octop_home: Path,
) -> None:
    """Disabling the wizard password gate no longer re-opens account creation."""
    write_octop_config(tmp_octop_home, require_setup_password=False)

    async with octop_client(tmp_octop_home) as (c, _srv):
        await _assert_retired(
            await c.post(
                "/api/setup/initial-admin",
                json={"username": "local"},
                headers={"Authorization": "Bearer local-owner"},
            )
        )


async def test_initial_admin_respects_locale_body(env: Any) -> None:
    """No account is written, so the posted ``locale`` never reaches user storage."""
    c, srv, _home = env
    await _assert_retired(
        await c.post(
            "/api/setup/initial-admin",
            json={"username": "admin", "password": "TestPass12", "locale": "en"},
            headers={"Authorization": "Bearer local-owner"},
        )
    )
    assert srv.user_manager.get("admin") is None


# ─── /setup/status ─────────────────────────────────────────────────


async def test_status_reports_wizard_password_exists(env: Any) -> None:
    c, srv, _auth = env
    home = srv.paths.root
    body = (await c.get("/api/setup/status")).json()
    assert body["setup_required"] is False
    assert body["wizard_password_required"] is False
    assert body["wizard_password_exists"] is False
    assert "wizard_password_path" not in body
    assert body["local_account"] is True
    assert body["single_user"] is True
    assert not (home / WIZARD_FILE_NAME).exists()


async def test_begin_issues_token_when_password_not_required(tmp_octop_home: Path) -> None:
    write_octop_config(tmp_octop_home, require_setup_password=False)

    async with octop_client(tmp_octop_home) as (c, _srv):
        body = (await c.get("/api/setup/status")).json()
        assert body["wizard_password_required"] is False
        assert body["wizard_password_exists"] is False
        assert "wizard_password_path" not in body

        await _assert_retired(await c.post("/api/setup/begin"))


async def test_validate_token_rejects_missing_header(env: Any) -> None:
    c, _srv, _home = env
    r = await c.get("/api/setup/validate-token")
    assert r.status_code == 200
    assert r.json()["valid"] is False


async def test_validate_token_accepts_fresh_token(env: Any) -> None:
    """There is no token store any more: every token is invalid."""
    c, _srv, _home = env
    r = await c.get(
        "/api/setup/validate-token",
        headers={"Authorization": "Bearer local-owner"},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is False


async def test_validate_token_rejects_stale_token(env: Any) -> None:
    c, _srv, _home = env
    r = await c.get(
        "/api/setup/validate-token",
        headers={"Authorization": "Bearer stale-token"},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is False


# ─── /setup/finish ─────────────────────────────────────────────────


async def test_finish_requires_wizard_token(env: Any) -> None:
    c, _srv, _home = env
    await _assert_retired(await c.post("/api/setup/finish", json={"provider_draft": None}))


async def test_finish_returns_ok_with_valid_token(env: Any) -> None:
    c, _srv, _home = env
    await _assert_retired(
        await c.post(
            "/api/setup/finish",
            json={"provider_draft": None},
            headers={"Authorization": "Bearer local-owner"},
        )
    )


async def test_finish_works_after_admin_created(env: Any) -> None:
    c, _srv, _home = env
    await _assert_retired(
        await c.post(
            "/api/setup/finish",
            json={"provider_draft": None},
            headers={"Authorization": "Bearer local-owner"},
        )
    )


async def test_validate_token_still_valid_after_admin_created(env: Any) -> None:
    c, _srv, _home = env
    r = await c.get(
        "/api/setup/validate-token",
        headers={"Authorization": "Bearer local-owner"},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is False


async def test_test_provider_requires_wizard_token(env: Any) -> None:
    """Provider drafting stays usable and needs no wizard token any more."""
    c, _srv, _home = env
    r = await c.post(
        "/api/setup/test-provider",
        json={
            "name": "OpenAI",
            "type": "openai",
            "api_key": "",
            "model_id": "gpt-4o-mini",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


async def test_test_provider_returns_error_for_empty_key(env: Any) -> None:
    c, _srv, _home = env
    r = await c.post(
        "/api/setup/test-provider",
        json={
            "name": "OpenAI",
            "type": "openai",
            "api_key": "  ",
            "model_id": "gpt-4o-mini",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


def _assert_resume_wizard_absent(response: Any) -> None:
    """A removed POST is 404, or 405 when the GET-only SPA catch-all is mounted."""
    assert response.status_code in (404, 405)
    assert "wizard_token" not in response.text


async def test_resume_wizard_does_not_issue_token(env: Any) -> None:
    c, _srv, _home = env
    _assert_resume_wizard_absent(await c.post("/api/setup/resume-wizard"))
    _assert_resume_wizard_absent(await c.post("/api/setup/resume-wizard"))


async def test_test_provider_accepts_admin_jwt_after_admin_created(env: Any) -> None:
    c, _srv, _home = env
    r = await c.post(
        "/api/setup/test-provider",
        json={
            "name": "OpenAI",
            "type": "openai",
            "api_key": "",
            "model_id": "gpt-4o-mini",
        },
        headers={"Authorization": "Bearer local-jwt"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


async def test_finish_saves_provider_with_admin_jwt(env: Any) -> None:
    """The retired route must not persist a provider draft as a side effect."""
    c, srv, _home = env
    await _assert_retired(
        await c.post(
            "/api/setup/finish",
            json={
                "provider_draft": {
                    "name": "HAI",
                    "type": "openai",
                    "api_key": "sk-test",
                    "base_url": "https://api.example.com/v1",
                    "models": [
                        {
                            "id": "MiniMax-M2.7",
                            "name": "MiniMax",
                            "enabled": True,
                            "input": ["text"],
                        }
                    ],
                }
            },
            headers={"Authorization": "Bearer local-jwt"},
        )
    )
    assert srv.services.provider_repo.list_all() == []


# ─── retired 410 guard ─────────────────────────────────────────────


async def test_setup_410_after_admin_exists(env: Any) -> None:
    """The wizard is gone for every install; there is no completed-setup 410."""
    c, srv, _auth = env
    home = srv.paths.root
    r = await c.post("/api/setup/verify-password", json={"password": "stale"})
    await _assert_retired(r)
    # No password file is created or deleted by the app any more.
    assert not (home / WIZARD_FILE_NAME).exists()


async def test_desktop_can_add_local_account_beside_existing_users(
    tmp_octop_home: Path, monkeypatch: Any
) -> None:
    """The desktop-only account path is retired together with multi-account support."""
    write_octop_config(tmp_octop_home, require_setup_password=False)
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")

    async with octop_client(tmp_octop_home) as (c, _srv):
        await _assert_retired(await c.post("/api/setup/begin"))
        await _assert_retired(
            await c.post(
                "/api/setup/initial-admin",
                json={"username": "admin"},
                headers={"Authorization": "Bearer local-owner"},
            )
        )
        visible = (await c.get("/api/setup/status")).json()
        assert visible["local_account"] is True

        monkeypatch.delenv("OCTOP_DESKTOP_SHELL", raising=False)
        hidden = (await c.get("/api/setup/status")).json()
        assert hidden["local_account"] is True


# ─── lockdown middleware ───────────────────────────────────────────


async def test_lockdown_blocks_non_setup_endpoints_when_no_users(env: Any) -> None:
    """No users-exist gate: the local owner always exists, so agents stay reachable."""
    c, _srv, _home = env
    r = await c.get("/api/agents")
    assert r.status_code == 200


async def test_lockdown_allows_setup_endpoints(env: Any) -> None:
    c, _srv, _home = env
    r = await c.get("/api/setup/status")
    assert r.status_code == 200


async def test_lockdown_allows_health_path(env: Any) -> None:
    c, _srv, _home = env
    r = await c.get("/api/health")
    assert r.status_code == 200


async def test_lockdown_lifts_after_admin_created(env: Any) -> None:
    """Single-user requests resolve to the local owner even without a JWT."""
    c, _srv, _home = env
    r = await c.get("/api/agents")
    assert r.status_code == 200


async def test_finish_rejects_invalid_token_after_admin_exists(env: Any) -> None:
    c, _srv, _home = env
    await _assert_retired(
        await c.post(
            "/api/setup/finish",
            json={"provider_draft": None},
            headers={"Authorization": "Bearer faketoken"},
        )
    )


async def test_wizard_password_relocated_to_octop_home(env: Any) -> None:
    """Single-user mode never writes ``octop-login.txt`` into any home."""
    _c, srv, _auth = env
    home = srv.paths.root
    assert not (home / WIZARD_FILE_NAME).exists()
    assert not (Path.home() / WIZARD_FILE_NAME).exists()
    assert read_password(home) is None
