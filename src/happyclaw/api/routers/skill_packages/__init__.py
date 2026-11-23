"""Global skill-package HTTP API.

Split by responsibility; the package keeps the old module's namespace and
the ``/skill-packages`` prefix:

  crud    package CRUD, avatars and create-from-SkillHub
  hub     SkillHub search and rankings used by the package picker
  skills  package skills: read, tree, download, export and install"""

from __future__ import annotations

from fastapi import APIRouter

from happyclaw.api.routers.skill_packages.common import (
    _SAFE_SKILLHUB_REASONS,
    CreatePackageSkillBody,
    CreateSkillPackageBody,
    FromSkillHubBody,
    HubInstallPackageSkillBody,
    ImportPackageSkillBody,
    LocalizedSkillCopy,
    SkillFilePart,
    UpdatePackageSkillBody,
    UpdateSkillPackageBody,
    _assert_group_visible,
    _creator_fields,
    _display_package_icon_url,
    _files_from_package_skill_body,
    _icon_url,
    _is_package_avatar_url,
    _map_skillhub_error,
    _package_access,
    _package_avatar_api_path,
    _package_avatars,
    _package_or_404,
    _package_owner,
    _package_payload,
    _package_payload_with_creator,
    _package_skill_exists,
    _package_skill_or_404,
    _package_visible_or_404,
    _required,
    _row_public_dict,
    _store,
    _visible_packages,
)
from happyclaw.api.routers.skill_packages.crud import (
    create_from_skillhub,
    create_skill_package,
    delete_skill_package,
    delete_skill_package_avatar,
    get_skill_package,
    get_skill_package_avatar,
    list_skill_packages,
    update_skill_package,
    upload_skill_package_avatar,
)
from happyclaw.api.routers.skill_packages.crud import router as crud_router
from happyclaw.api.routers.skill_packages.hub import package_hub_rankings, package_hub_search
from happyclaw.api.routers.skill_packages.hub import router as hub_router
from happyclaw.api.routers.skill_packages.skills import (
    _package_has_skill,
    _PackageInstallTarget,
    _read_package_skill_files,
    _refresh_package,
    create_package_skill,
    delete_package_skill,
    download_package_skill_file,
    export_skill_package,
    get_package_skill,
    hub_install_package_skill,
    import_package_skill,
    list_package_skill_tree,
    list_package_skills,
    read_package_skill_file,
    update_package_skill,
)
from happyclaw.api.routers.skill_packages.skills import router as skills_router

router = APIRouter()
router.include_router(crud_router, prefix="/skill-packages")
router.include_router(hub_router, prefix="/skill-packages")
router.include_router(skills_router, prefix="/skill-packages")

__all__ = [
    "router",
    "CreatePackageSkillBody",
    "CreateSkillPackageBody",
    "FromSkillHubBody",
    "HubInstallPackageSkillBody",
    "ImportPackageSkillBody",
    "LocalizedSkillCopy",
    "SkillFilePart",
    "UpdatePackageSkillBody",
    "UpdateSkillPackageBody",
    "_PackageInstallTarget",
    "_SAFE_SKILLHUB_REASONS",
    "_assert_group_visible",
    "_creator_fields",
    "_display_package_icon_url",
    "_files_from_package_skill_body",
    "_icon_url",
    "_is_package_avatar_url",
    "_map_skillhub_error",
    "_package_access",
    "_package_avatar_api_path",
    "_package_avatars",
    "_package_has_skill",
    "_package_or_404",
    "_package_owner",
    "_package_payload",
    "_package_payload_with_creator",
    "_package_skill_exists",
    "_package_skill_or_404",
    "_package_visible_or_404",
    "_read_package_skill_files",
    "_refresh_package",
    "_required",
    "_row_public_dict",
    "_store",
    "_visible_packages",
    "create_from_skillhub",
    "create_package_skill",
    "create_skill_package",
    "delete_package_skill",
    "delete_skill_package",
    "delete_skill_package_avatar",
    "download_package_skill_file",
    "export_skill_package",
    "get_package_skill",
    "get_skill_package",
    "get_skill_package_avatar",
    "hub_install_package_skill",
    "import_package_skill",
    "list_package_skill_tree",
    "list_package_skills",
    "list_skill_packages",
    "package_hub_rankings",
    "package_hub_search",
    "read_package_skill_file",
    "update_package_skill",
    "update_skill_package",
    "upload_skill_package_avatar",
]
