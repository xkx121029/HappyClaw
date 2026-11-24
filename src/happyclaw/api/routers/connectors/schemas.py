"""Request bodies for the connector routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CreateInstanceBody(BaseModel):
    kind: str
    display_name: str
    description: str | None = Field(default=None, max_length=500)
    credentials: dict[str, Any] = Field(default_factory=dict)
    shared: bool = False
    visibility: Literal["owner", "all", "groups"] | None = Field(
        default=None,
        description="Who may use this instance. When set, overrides ``shared``.",
    )
    group_ids: list[str] | None = None
    default_open: bool = Field(
        default=False,
        description=(
            "Per-account default: when true, inject this connector's tools for "
            "the owner on IM and on Cron jobs with no explicit connector picks. "
            "Dashboard and Cron with explicit picks follow the selection."
        ),
    )


class PatchInstanceBody(BaseModel):
    status: str | None = None
    display_name: str | None = None
    description: str | None = Field(default=None, max_length=500)
    credentials: dict[str, Any] | None = None
    shared: bool | None = None
    visibility: Literal["owner", "all", "groups"] | None = Field(
        default=None,
        description="Who may use this instance. When set, overrides ``shared``.",
    )
    group_ids: list[str] | None = None
    default_open: bool | None = Field(
        default=None,
        description=(
            "When set, update per-account default-open. IM / empty Cron follow "
            "it for this user; Dashboard and Cron with explicit picks use the "
            "selection."
        ),
    )


class OAuthStartBody(BaseModel):
    redirect_after: str | None = None
    target: dict[str, Any] | None = Field(
        default=None,
        description='OAuth target, e.g. {"type":"catalog","kind":"notion"} or '
        '{"type":"custom_mcp","server_name":"my-server"}',
    )


class OAuthStartLegacyBody(BaseModel):
    redirect_after: str | None = None


class ExchangeAuthCodeBody(BaseModel):
    code: str
    bkn: str | None = None
    knowledge_base_id: str | None = None


class TestCredentialsBody(BaseModel):
    kind: str
    credentials: dict[str, Any] = Field(default_factory=dict)


class FeishuUserAuthStartBody(BaseModel):
    app_id: str
    app_secret: str
    cli_config_key: str | None = None
    domains: list[str] | None = None


class FeishuUserAuthCompleteBody(BaseModel):
    app_id: str
    app_secret: str
    device_code: str
    cli_config_key: str | None = None


class AgentlyAuthResponse(BaseModel):
    status: Literal["idle", "pending", "authorized", "expired", "error"]
    verification_url: str | None = Field(default=None, description="Device authorization URL")
    user_code: str | None = Field(default=None, description="Code shown for device authorization")
    expires_at: int | None = Field(default=None, description="Pending flow expiry, Unix seconds")
    error: str | None = Field(default=None, description="Localized error, without CLI credentials")


class CustomMcpPutBody(BaseModel):
    servers: dict[str, Any] = Field(default_factory=dict)


class CustomMcpServerPatchBody(BaseModel):
    enabled: bool | None = None
    default_open: bool | None = None
    shared: bool | None = None

    @model_validator(mode="after")
    def _require_one_field(self) -> CustomMcpServerPatchBody:
        if self.enabled is None and self.default_open is None and self.shared is None:
            raise ValueError("provide enabled, default_open and/or shared")
        return self


class CustomMcpTestBody(BaseModel):
    """Probe one server by name (saved) or by inline spec."""

    name: str | None = None
    server: dict[str, Any] | None = None
