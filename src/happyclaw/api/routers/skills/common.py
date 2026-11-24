"""Agent context resolution plus the skill helpers shared by every route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from happyclaw.api.common.agent import require_agent_owner_row, require_agent_row
from happyclaw.infra.agents.manager import skill_package_ids_list
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.skills.presentation import apply_skill_presentation
from happyclaw.infra.skills.skill_package_store import SkillPackageStore
from happyclaw.infra.utils.frontmatter import parse_frontmatter
from happyclaw.infra.utils.locale import Locale

_BUILTIN_ROOT = "_builtin_skills"
_SKILLS_ROOT = "skills"


@dataclass
class _AgentCtx:
    runtime: Any
    workspace: Any
    config: dict[str, Any]


async def _ctx(
    agent_id: str,
    *,
    user: Any,
    as_user: int | None,
    server: Any,
    owner_only: bool = True,
) -> _AgentCtx:
    assert server.app_runtime is not None
    registry = server.app_runtime.agent_registry
    require = require_agent_owner_row if owner_only else require_agent_row
    row = require(agent_id, user=user, as_user=as_user, server=server)
    cfg = registry.get_config(agent_id)
    agent = registry.get_agent(agent_id)
    return _AgentCtx(runtime=row, workspace=agent.workspace, config=cfg)


async def _aread_text(workspace: Any, path: str) -> str | None:
    return cast(str | None, await workspace.aread_text(path))


async def _aoverwrite_text(workspace: Any, path: str, content: str) -> str | None:
    try:
        await workspace.awrite_text(path, content, force=True)
    except Exception as exc:
        return f"{exc}"
    return None


def _summary_dict(
    name: str,
    meta: dict[str, Any],
    *,
    enabled: bool,
    kind: str,
    locale: Locale | None = None,
) -> dict[str, Any]:
    out = apply_skill_presentation(
        {
            # ``slug`` is the directory name — the stable identifier used for all
            # by-name operations (detail / enable / disable / delete / install
            # check). ``name`` is the frontmatter display name, which may differ
            # from the slug (e.g. dir "tencent-meeting-skill" with frontmatter
            # name "tencent-meeting-mcp"); using ``name`` as the id 404s.
            "slug": name,
            "name": str(meta.get("name") or name),
            "description": str(meta.get("description") or ""),
            "enabled": enabled,
            "kind": kind,
        },
        meta,
        locale=locale,
    )
    return out


def _valid_skillhub_icon_url(value: str) -> bool:
    from happyclaw.infra.skills.install import valid_skillhub_icon_url  # noqa: PLC0415

    return valid_skillhub_icon_url(value)


def _skill_manifest_path(name: str, kind: str, workspace: Any) -> str:
    root = _BUILTIN_ROOT if kind == "builtin" else _SKILLS_ROOT
    return f"{root}/{name}/SKILL.md"


async def _resolve_skill(
    workspace: Any,
    name: str,
) -> tuple[str, str, str] | None:
    """Resolve a skill by name. Workspace entries override builtin names."""
    for kind in ("workspace", "builtin"):
        manifest_path = _skill_manifest_path(name, kind, workspace)
        manifest = await _aread_text(workspace, manifest_path)
        if manifest is None:
            continue
        meta, body = parse_frontmatter(manifest)
        if meta.get("removed"):
            continue
        return manifest_path, kind, body
    return None


async def _guard_package_only_skill_write(
    workspace: Any,
    config: dict[str, Any],
    server: Any,
    slug: str,
    user: Any = None,
) -> None:
    """Reject writes that would alter a skill supplied only by a mounted package.

    Also rejects writes to workspace copies stamped ``locked`` by a
    ``copy_policy="lock"`` package unless the requester created that package
    (or is admin) — the copy is meant to be used, not rewritten (#770).
    """
    workspace_manifest = await _aread_text(workspace, f"{_SKILLS_ROOT}/{slug}/SKILL.md")
    if workspace_manifest is not None:
        metadata, _body = parse_frontmatter(workspace_manifest)
        if not metadata.get("removed"):
            origin = str(metadata.get("origin") or "").strip()
            if metadata.get("locked") and origin and server.services is not None:
                store = _skill_package_store(server)
                origin_row = store.repo.get(origin)
                # Unknown origin stays locked for regular users (fail-safe)
                # but admins keep an escape hatch for orphaned copies.
                allowed = bool(getattr(user, "is_admin", False)) or (
                    user is not None
                    and origin_row is not None
                    and str(getattr(user, "id", "")) == origin_row.created_by
                )
                if not allowed:
                    raise HappyclawError(
                        ErrorCode.SKILL_PACKAGE_LOCKED,
                        f"skill {slug!r} was copied from a locked skill package",
                    )
            return

    assert server.services is not None
    store = _skill_package_store(server)
    for package_id in skill_package_ids_list(config):
        if any(skill["slug"] == slug for skill in store.list_skill_summaries(package_id)):
            raise HappyclawError(
                ErrorCode.FORBIDDEN,
                f"skill {slug!r} is supplied by a mounted package",
            )


async def _enabled_skill_names(
    server: Any,
    *,
    agent_id: str,
    user: Any,
) -> set[str]:
    """Return installed, non-disabled skill names for an agent."""
    await _ctx(agent_id, user=user, as_user=None, server=server, owner_only=False)
    assert server.app_runtime is not None
    names: set[str] = set()
    for summary in await server.app_runtime.agent_registry.list_skill_summaries(agent_id):
        if summary.get("enabled"):
            names.add(str(summary["name"]))
            slug = summary.get("slug")
            if slug:
                names.add(str(slug))
    return names


async def validate_chat_skills(
    server: Any,
    *,
    agent_id: str,
    user: Any,
    names: list[str] | None,
) -> list[str] | None:
    from happyclaw.api.common.validators import validate_chat_skills as _validate

    return await _validate(server, agent_id=agent_id, user=user, names=names)


def _skill_package_store(server: Any) -> SkillPackageStore:
    if server.services is None:
        raise HappyclawError(ErrorCode.INTERNAL_ERROR, "skill package store not initialized")
    config = getattr(server.services, "config", None)
    database = getattr(config, "database", None) if config is not None else None
    return SkillPackageStore(
        repo=server.services.skill_package_repo,
        root=server.paths.skill_packages_dir,
        database=database,
    )
