"""Setup endpoints for the single-user local runtime.

There is no first-run wizard anymore: a clean ``HAPPYCLAW_HOME`` binds the default
SQLite control plane at boot and the local owner is created automatically. The
historical paths stay mounted so an older dashboard/desktop build gets a clear
Chinese answer instead of a 404 or a dead setup page.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from happyclaw.api.deps import get_server
from happyclaw.infra.errors import ErrorCode, HappyclawError

logger = logging.getLogger(__name__)

router = APIRouter()


class ProviderTestBody(BaseModel):
    name: str
    type: str
    api_key: str = ""
    base_url: str | None = None
    model_id: str = Field(min_length=1)


class DatabaseSetupBody(BaseModel):
    driver: str = Field(description="sqlite | postgresql")
    sqlite_path: str | None = None
    host: str | None = None
    port: int = 5432
    database: str | None = None
    user: str | None = None
    password: str | None = None
    url: str | None = None
    adopt_existing: bool = False

    def as_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"driver": self.driver.strip().lower()}
        for key in ("sqlite_path", "host", "database", "user", "password", "url"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        out["port"] = self.port
        return out


def _single_user(message: str = "单人模式无需初始化账号") -> HappyclawError:
    """Uniform Chinese refusal for wizard-only write endpoints."""
    err = HappyclawError(ErrorCode.SINGLE_USER_UNSUPPORTED, message)
    err.message = message
    return err


@router.get("/setup/presets", summary="List provider presets")
async def setup_presets() -> list[dict[str, Any]]:
    """Built-in LLM provider templates (kept for the model settings screen)."""
    # Imported lazily: the providers package pulls the agent stack (harness →
    # langchain), which must stay off the pre-listen import path.
    from happyclaw.infra.agents.providers.presets import load_provider_presets  # noqa: PLC0415

    return load_provider_presets()


@router.get("/setup/validate-token", summary="Check wizard session token")
async def validate_wizard_token() -> dict[str, bool]:
    """Wizard tokens no longer exist; always invalid."""
    return {"valid": False}


@router.get("/setup/status", summary="Setup wizard status")
async def status(server: Any = Depends(get_server)) -> dict[str, Any]:
    """Single-user: setup is always complete, no wizard password is involved."""
    database_driver = None
    if server.database_bound and server.services is not None:
        database_driver = server.services.config.database.driver
    return {
        # Fixed values so the dashboard never routes to the setup page.
        "setup_required": False,
        "local_account": True,
        "wizard_password_required": False,
        "wizard_password_exists": False,
        "database_driver": database_driver,
        "database_bound": server.database_bound,
        "single_user": True,
    }


@router.post("/setup/test-database", summary="Probe control-plane database connectivity")
async def test_database(
    body: DatabaseSetupBody, server: Any = Depends(get_server)
) -> dict[str, Any]:
    """Read-only DSN probe; useful for diagnostics even in single-user mode."""
    from happyclaw.infra.db.probe import probe_database
    from happyclaw.infra.db.rebind import database_config_from_payload

    try:
        db_cfg = database_config_from_payload(body.as_payload())
    except ValueError as exc:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, str(exc)) from exc
    user_count = probe_database(db_cfg, server.paths)
    return {"ok": True, "driver": db_cfg.driver, "user_count": user_count}


@router.post("/setup/database", summary="Persist control-plane database and bind")
async def apply_database() -> dict[str, Any]:
    """Single-user: the SQLite control plane is fixed; no backend picker."""
    raise _single_user("单人模式固定使用本地 SQLite，无需选择数据库后端")


@router.post("/setup/begin", summary="Begin setup without wizard password")
async def begin_setup() -> dict[str, Any]:
    raise _single_user()


@router.post("/setup/verify-password", summary="Verify wizard password")
async def verify_password() -> dict[str, Any]:
    raise _single_user("单人模式无需向导密码")


@router.post("/setup/initial-admin", status_code=201, summary="Create initial admin")
async def initial_admin() -> dict[str, Any]:
    raise _single_user("单人模式已自动创建本机使用者，无需再创建管理员")


@router.post("/setup/finish", summary="Finish setup wizard")
async def finish() -> dict[str, Any]:
    raise _single_user("单人模式无需完成初始化向导")


@router.post("/setup/test-provider", summary="Test provider draft connectivity")
async def test_provider_draft(
    body: ProviderTestBody,
    request: Request,
) -> dict[str, Any]:
    """Probe LLM connectivity for an unsaved provider draft."""
    if not body.api_key.strip():
        return {"ok": False, "error": "请填写 API Key"}
    from happyclaw.infra.agents.providers.probe import (  # noqa: PLC0415
        make_probe_provider_row,
        probe_provider_row,
    )

    row = make_probe_provider_row(
        name=body.name,
        kind=body.type,
        api_key=body.api_key or None,
        base_url=body.base_url,
        model_id=body.model_id,
    )
    from happyclaw.infra.utils.locale import resolve_request_locale

    return await probe_provider_row(row, locale=resolve_request_locale(request))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
