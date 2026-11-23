"""Request bodies plus the visibility, avatar and SkillHub error helpers."""

from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, Field

from happyclaw.infra.agents.experts.skillhub_market import SkillHubMarketErrorKind
from happyclaw.infra.db.repos.skill_packages import SkillPackageRow
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.server import HappyclawServer
from happyclaw.infra.skills.install import valid_skillhub_icon_url
from happyclaw.infra.skills.skill_package_store import SkillPackageStore
from happyclaw.infra.users.groups import RESOURCE_SKILL_PACKAGE, GroupAccess
from happyclaw.infra.users.identity import User
from happyclaw.infra.utils.locale import Locale

_SAFE_SKILLHUB_REASONS: dict[SkillHubMarketErrorKind, str] = {
    SkillHubMarketErrorKind.NOT_FOUND: "skillset not found",
    SkillHubMarketErrorKind.INVALID_SLUG: "invalid skillset id",
    SkillHubMarketErrorKind.UPSTREAM_TIMEOUT: "upstream timeout",
    SkillHubMarketErrorKind.UPSTREAM_BAD_PAYLOAD: "invalid upstream response",
    SkillHubMarketErrorKind.PACKAGE_INVALID: "invalid skillset package",
    SkillHubMarketErrorKind.PACKAGE_TOO_LARGE: "skillset package too large",
    SkillHubMarketErrorKind.UPSTREAM_FAILED: "upstream request failed",
    SkillHubMarketErrorKind.SSL_ERROR: "ssl error",
}


class CreateSkillPackageBody(BaseModel):
    name: str
    description: str = ""
    icon_name: str = ""
    icon_url: str = ""
    shared: bool = False
    visibility: Literal["all", "groups", "owner"] | None = None
    group_ids: list[str] | None = None
    copy_policy: Literal["snapshot", "lock", "deny"] = "snapshot"
    allow_download: bool = True


class UpdateSkillPackageBody(BaseModel):
    name: str | None = None
    description: str | None = None
    icon_name: str | None = None
    icon_url: str | None = None
    shared: bool | None = None
    copy_policy: Literal["snapshot", "lock", "deny"] | None = Field(
        default=None,
        description=(
            "Controls copying package skills into an agent workspace for users who "
            "can already view the package (including the owner's other experts)."
        ),
    )
    allow_download: bool | None = Field(
        default=None,
        description="When false, non-owner users who can view the package cannot export a ZIP.",
    )
    visibility: Literal["all", "groups", "owner"] | None = None
    group_ids: list[str] | None = None


class FromSkillHubBody(BaseModel):
    slug: str
    name: str | None = None
    description: str | None = None
    icon_name: str | None = None
    icon_url: str | None = None
    shared: bool = False


class SkillFilePart(BaseModel):
    path: str
    content_base64: str


class CreatePackageSkillBody(BaseModel):
    name: str
    content: str = ""
    files: list[SkillFilePart] | None = None
    overwrite: bool = False


class UpdatePackageSkillBody(BaseModel):
    content: str = ""
    files: list[SkillFilePart] | None = None


class ImportPackageSkillBody(BaseModel):
    bundle_url: str
    version: str = ""
    overwrite: bool = False


def _files_from_package_skill_body(
    *,
    content: str,
    files: list[SkillFilePart] | None,
) -> list[tuple[str, bytes]]:
    if files:
        decoded: list[tuple[str, bytes]] = []
        for part in files:
            try:
                decoded.append((part.path, base64.b64decode(part.content_base64, validate=True)))
            except Exception as exc:
                raise HappyclawError(
                    ErrorCode.SLASH_BAD_ARGS,
                    f"invalid base64 content for {part.path!r}",
                ) from exc
        return decoded
    if not content:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, "content or files is required")
    return [("SKILL.md", content.encode("utf-8"))]


def _package_skill_exists(store: SkillPackageStore, package_id: str, slug: str) -> bool:
    return store.has_skill(package_id, slug)


class LocalizedSkillCopy(BaseModel):
    zh: str | None = None
    en: str | None = None


class HubInstallPackageSkillBody(BaseModel):
    skill_name: str
    display_name: str | None = None
    icon_url: str | None = None
    label: LocalizedSkillCopy | None = None
    summary: LocalizedSkillCopy | None = None
    overwrite: bool = False


def _store(server: HappyclawServer) -> SkillPackageStore:
    if server.services is None:
        raise HappyclawError(ErrorCode.INTERNAL_ERROR, "skill package store not initialized")
    return SkillPackageStore(
        repo=server.services.skill_package_repo,
        root=server.paths.skill_packages_dir,
        database=server.services.config.database,
    )


def _package_or_404(
    store: SkillPackageStore,
    package_id: str,
    *,
    locale: str,
) -> SkillPackageRow:
    row = store.repo.get(package_id)
    if row is None:
        raise HappyclawError.localized(ErrorCode.SKILL_PACKAGE_NOT_FOUND, locale)
    return row


def _package_avatars(server: HappyclawServer) -> Any:
    assert server.services is not None
    return server.services.avatars("skill_package")


def _package_avatar_api_path(package_id: str) -> str:
    return f"/api/skill-packages/{package_id}/avatar"


def _is_package_avatar_url(value: str, package_id: str | None = None) -> bool:
    path = value.strip().split("?", 1)[0]
    if package_id:
        return path == _package_avatar_api_path(package_id)
    return path.startswith("/api/skill-packages/") and path.endswith("/avatar")


def _display_package_icon_url(server: HappyclawServer, row: SkillPackageRow) -> str:
    from happyclaw.infra.users.profile_avatar import profile_avatar_url  # noqa: PLC0415

    text = str(row.icon_url or "").strip()
    api = _package_avatar_api_path(row.id)
    if text.split("?", 1)[0] == api:
        return profile_avatar_url(_package_avatars(server), row.id, api) or api
    return text


def _row_public_dict(server: HappyclawServer, row: SkillPackageRow) -> dict[str, Any]:
    payload = asdict(row)
    payload.pop("pk", None)
    payload["icon_url"] = _display_package_icon_url(server, row)
    return payload


def _package_payload(
    store: SkillPackageStore,
    row: SkillPackageRow,
    *,
    locale: Locale | None = None,
    server: HappyclawServer | None = None,
) -> dict[str, Any]:
    if server is None:
        payload = asdict(row)
        payload.pop("pk", None)
    else:
        payload = _row_public_dict(server, row)
    return {
        **payload,
        "skills": store.list_skill_summaries(row.id, locale=locale),
    }


def _package_access(server: HappyclawServer) -> GroupAccess:
    assert server.services is not None
    return GroupAccess(server.services.repos)


def _package_owner(user: User, row: SkillPackageRow) -> bool:
    return str(user.id) == str(row.created_by)


def _creator_fields(server: HappyclawServer, created_by: str) -> dict[str, str | None]:
    raw = str(created_by or "").strip()
    if not raw.isdigit():
        return {"creator_username": None, "creator_display_name": None}
    if server.services is None:
        return {"creator_username": None, "creator_display_name": None}
    owner = server.services.user_repo.get(int(raw))
    if owner is None:
        return {"creator_username": None, "creator_display_name": None}
    return {
        "creator_username": owner.username,
        "creator_display_name": owner.display_name or owner.username,
    }


def _package_payload_with_creator(
    server: HappyclawServer,
    store: SkillPackageStore,
    row: SkillPackageRow,
    *,
    locale: Locale | None = None,
) -> dict[str, Any]:
    return {
        **_package_payload(store, row, locale=locale, server=server),
        **_creator_fields(server, row.created_by),
    }


def _required(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, f"{field} is required")
    return value


def _icon_url(value: str, *, package_id: str | None = None) -> str:
    value = value.strip()
    if len(value) > 2048:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, "icon_url is too long")
    if (
        value
        and not valid_skillhub_icon_url(value)
        and not _is_package_avatar_url(value, package_id)
    ):
        raise HappyclawError(
            ErrorCode.SLASH_BAD_ARGS,
            "icon_url must be an HTTP(S) URL or package avatar path",
        )
    return value


def _visible_packages(store: SkillPackageStore, user: User) -> list[SkillPackageRow]:
    if user.is_admin:
        return store.repo.list_all()
    return store.repo.list_visible(user.id)


def _assert_group_visible(
    server: HappyclawServer,
    user: User,
    row: SkillPackageRow,
    *,
    locale: str,
) -> None:
    """User groups only narrow packages the shared flag already exposes."""
    if _package_access(server).allows(
        user_id=user.id,
        is_admin=user.is_admin,
        resource_type=RESOURCE_SKILL_PACKAGE,
        resource_key=row.id,
        is_owner=_package_owner(user, row),
    ):
        return
    raise HappyclawError.localized(ErrorCode.SKILL_PACKAGE_NOT_FOUND, locale)


def _package_visible_or_404(
    store: SkillPackageStore,
    package_id: str,
    user: User,
    server: HappyclawServer,
    *,
    locale: str,
) -> SkillPackageRow:
    row = _package_or_404(store, package_id, locale=locale)
    store.assert_can_view(row, user)
    _assert_group_visible(server, user, row, locale=locale)
    return row


def _map_skillhub_error(exc: BaseException) -> HappyclawError:
    kind = getattr(exc, "kind", SkillHubMarketErrorKind.UPSTREAM_FAILED)
    if kind in (
        SkillHubMarketErrorKind.NOT_FOUND,
        SkillHubMarketErrorKind.INVALID_SLUG,
    ):
        return HappyclawError(ErrorCode.NOT_FOUND, "skillhub skillset not found")
    if kind == SkillHubMarketErrorKind.SSL_ERROR:
        return HappyclawError(
            ErrorCode.SKILLHUB_SSL_FAILED,
            "skillhub ssl error",
            details={"reason": "ssl_error", "kind": kind.value},
        )
    reason = _SAFE_SKILLHUB_REASONS.get(
        kind,
        _SAFE_SKILLHUB_REASONS[SkillHubMarketErrorKind.UPSTREAM_FAILED],
    )
    return HappyclawError(
        ErrorCode.EXPERT_MARKET_FAILED,
        f"skillhub market failed: {reason}",
        details={"reason": reason, "kind": kind.value},
    )


def _package_skill_or_404(
    store: SkillPackageStore,
    package_id: str,
    slug: str,
    *,
    locale: Locale | None = None,
) -> dict[str, Any]:
    for skill in store.list_skill_summaries(
        package_id,
        locale=locale,
    ):
        if skill["slug"] == slug:
            return skill
    raise HappyclawError(ErrorCode.NOT_FOUND, f"skill {slug!r} not found")
