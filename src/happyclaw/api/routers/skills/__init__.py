"""Skills router — per-agent ``SKILL.md`` library.

Each agent's skills live under its harness backend at ``/skills/<name>/SKILL.md``
(matching finnie's convention). This package thinly wraps the workspace
backend so the dashboard sees a *named* skills view rather than a raw
file listing:

  GET    /api/agents/{aid}/skills                 → summaries
  GET    /api/agents/{aid}/skills/{name}          → full detail (frontmatter + body)
  GET    /api/agents/{aid}/skills/{name}/export   → ZIP of one workspace skill
  POST   /api/agents/{aid}/skills/export          → ZIP of selected workspace skills
  POST   /api/agents/{aid}/skills                 → body { name, content }
  DELETE /api/agents/{aid}/skills/{name}          → remove SKILL.md
  POST   /api/agents/{aid}/skills/{name}/enable
  POST   /api/agents/{aid}/skills/{name}/disable

A skill is considered "enabled" unless its slug is listed in
``agent.config.skills_disabled``. The enable/disable endpoints toggle
that list and hot-sync ``HarnessAgentConfig.skills_disabled`` so
``SkillFilterMiddleware`` excludes disabled skills on every turn.

Limitations
-----------
The protocol has no ``delete``: removing a skill rewrites SKILL.md to
an empty file with the leading frontmatter block ``---\\nremoved: true\\n---``
so the directory listing still shows the entry but the dashboard knows
to filter it. This is a deliberate design compromise — protocol-level
delete is the right long-term answer.

Split by responsibility; the package keeps the old module's namespace."""

from __future__ import annotations

from fastapi import APIRouter

from happyclaw.api.routers.skills.common import (
    _BUILTIN_ROOT,
    _SKILLS_ROOT,
    _AgentCtx,
    _aoverwrite_text,
    _aread_text,
    _ctx,
    _enabled_skill_names,
    _guard_package_only_skill_write,
    _resolve_skill,
    _skill_manifest_path,
    _skill_package_store,
    _summary_dict,
    _valid_skillhub_icon_url,
    validate_chat_skills,
)
from happyclaw.api.routers.skills.crud import (
    CreateSkillBody,
    ImportSkillBody,
    SkillFilePart,
    UpdateSkillBody,
    _files_from_skill_body,
    _persist_disabled,
    _skill_disable_keys,
    _write_skill_files,
    create_skill,
    delete_skill,
    disable_skill,
    enable_skill,
    get_skill,
    list_skills,
    update_skill,
)
from happyclaw.api.routers.skills.crud import router as crud_router
from happyclaw.api.routers.skills.hub import (
    _RANKING_TYPES,
    HubInstallBody,
    LocalizedSkillCopy,
    _hub_rankings,
    _hub_search,
    hub_install_skill,
    hub_rankings,
    hub_rankings_global,
    hub_search_skills,
    hub_search_skills_global,
)
from happyclaw.api.routers.skills.hub import router as hub_router
from happyclaw.api.routers.skills.package_mounts import (
    CopyPackageSkillsBody,
    CopyWorkspaceSkillBody,
    PushSkillToPackageBody,
    SkillPackageMountBody,
    _assert_skill_package_group,
    _skill_transfer_error,
    copy_skill_package_to_workspace,
    list_skill_package_mounts,
    push_workspace_skill_to_package,
    replace_skill_package_mounts,
)
from happyclaw.api.routers.skills.package_mounts import router as package_mounts_router
from happyclaw.api.routers.skills.transfer import (
    ExportSkillsBody,
    _AgentWorkspaceInstallTarget,
    copy_skill_from_agent,
    export_skill_zip,
    export_skills_zip,
    import_skill_from_url,
)
from happyclaw.api.routers.skills.transfer import router as transfer_router

router = APIRouter()
router.include_router(crud_router)
router.include_router(transfer_router)
router.include_router(package_mounts_router)
router.include_router(hub_router)

__all__ = [
    "router",
    "CopyPackageSkillsBody",
    "CopyWorkspaceSkillBody",
    "CreateSkillBody",
    "ExportSkillsBody",
    "HubInstallBody",
    "ImportSkillBody",
    "LocalizedSkillCopy",
    "PushSkillToPackageBody",
    "SkillFilePart",
    "SkillPackageMountBody",
    "UpdateSkillBody",
    "_AgentCtx",
    "_AgentWorkspaceInstallTarget",
    "_BUILTIN_ROOT",
    "_RANKING_TYPES",
    "_SKILLS_ROOT",
    "_aoverwrite_text",
    "_aread_text",
    "_assert_skill_package_group",
    "_ctx",
    "_enabled_skill_names",
    "_files_from_skill_body",
    "_guard_package_only_skill_write",
    "_hub_rankings",
    "_hub_search",
    "_persist_disabled",
    "_resolve_skill",
    "_skill_disable_keys",
    "_skill_manifest_path",
    "_skill_package_store",
    "_skill_transfer_error",
    "_summary_dict",
    "_valid_skillhub_icon_url",
    "_write_skill_files",
    "copy_skill_from_agent",
    "copy_skill_package_to_workspace",
    "create_skill",
    "delete_skill",
    "disable_skill",
    "enable_skill",
    "export_skill_zip",
    "export_skills_zip",
    "get_skill",
    "hub_install_skill",
    "hub_rankings",
    "hub_rankings_global",
    "hub_search_skills",
    "hub_search_skills_global",
    "import_skill_from_url",
    "list_skill_package_mounts",
    "list_skills",
    "push_workspace_skill_to_package",
    "replace_skill_package_mounts",
    "update_skill",
    "validate_chat_skills",
]
