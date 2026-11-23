"""Skills inside a package: read, tree, download, export, install and delete."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response

from happyclaw.api.common.content_disposition import content_disposition
from happyclaw.api.common.workspace import coerce_read_content
from happyclaw.api.deps import get_server, require_permission
from happyclaw.api.routers.skill_packages.common import (
    CreatePackageSkillBody,
    HubInstallPackageSkillBody,
    ImportPackageSkillBody,
    UpdatePackageSkillBody,
    _assert_group_visible,
    _files_from_package_skill_body,
    _package_or_404,
    _package_skill_exists,
    _package_skill_or_404,
    _package_visible_or_404,
    _required,
    _store,
)
from happyclaw.infra.agents.experts.skillhub_market import SkillHubMarketError
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.server import HappyclawServer
from happyclaw.infra.skills.install import valid_skillhub_icon_url
from happyclaw.infra.skills.skill_archive import build_skills_zip
from happyclaw.infra.skills.skill_package_store import SkillPackageStore
from happyclaw.infra.skills.skill_packages import SkillPackageError
from happyclaw.infra.users.identity import User
from happyclaw.infra.utils.frontmatter import parse_frontmatter
from happyclaw.infra.utils.locale import resolve_request_locale

router = APIRouter()

@router.get("/{package_id}/skills", summary="List skills in a global skill package")
async def list_package_skills(
    package_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> list[dict[str, Any]]:
    store = _store(server)
    locale = resolve_request_locale(request)
    _package_visible_or_404(store, package_id, user, server, locale=locale)
    return store.list_skill_summaries(package_id, locale=locale)


@router.get("/{package_id}/skills/{slug}", summary="Get a global package skill")
async def get_package_skill(
    package_id: str,
    slug: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    store = _store(server)
    locale = resolve_request_locale(request)
    _package_visible_or_404(store, package_id, user, server, locale=locale)
    skill = _package_skill_or_404(store, package_id, slug, locale=locale)
    raw = store.read_skill_file_text(package_id, slug, "SKILL.md")
    frontmatter, body = parse_frontmatter(raw)
    return {**skill, "frontmatter": frontmatter, "body": body, "raw": raw}


@router.get(
    "/{package_id}/skills/{slug}/tree",
    summary="List files under a global package skill path",
)
async def list_package_skill_tree(
    package_id: str,
    slug: str,
    request: Request,
    path: str = Query(default="", description="Path relative to the skill root"),
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> list[dict[str, Any]]:
    store = _store(server)
    locale = resolve_request_locale(request)
    _package_visible_or_404(store, package_id, user, server, locale=locale)
    _package_skill_or_404(store, package_id, slug, locale=locale)
    return await asyncio.to_thread(store.list_skill_tree, package_id, slug, path)


@router.get(
    "/{package_id}/skills/{slug}/file",
    summary="Read a UTF-8 text file from a global package skill",
)
async def read_package_skill_file(
    package_id: str,
    slug: str,
    path: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    store = _store(server)
    locale = resolve_request_locale(request)
    _package_visible_or_404(store, package_id, user, server, locale=locale)
    _package_skill_or_404(store, package_id, slug, locale=locale)
    content = await asyncio.to_thread(store.read_skill_file_text, package_id, slug, path)
    return {"path": path, "content": coerce_read_content(content)}


@router.get(
    "/{package_id}/skills/{slug}/download",
    summary="Download a file from a global package skill",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_package_skill_file(
    package_id: str,
    slug: str,
    path: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> Response:
    store = _store(server)
    locale = resolve_request_locale(request)
    _package_visible_or_404(store, package_id, user, server, locale=locale)
    _package_skill_or_404(store, package_id, slug, locale=locale)
    payload = await asyncio.to_thread(store.read_skill_file_bytes, package_id, slug, path)
    fname = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or "download.bin"
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={"Content-Disposition": content_disposition(fname)},
    )


def _read_package_skill_files(
    store: SkillPackageStore, package_id: str
) -> list[tuple[str, list[tuple[str, bytes]]]]:
    packed: list[tuple[str, list[tuple[str, bytes]]]] = []
    for summary in store.list_skill_summaries(package_id):
        if summary.get("corrupt"):
            continue
        slug = str(summary.get("slug") or "")
        packed.append((slug, store.read_skill_files(package_id, slug)))
    if not packed:
        raise SkillPackageError("skill package has no skills")
    return packed


@router.get(
    "/{package_id}/export",
    summary="Download a skill package as a ZIP",
    description=(
        "Pack every skill in the package into one ZIP. Each skill is a top-level "
        "folder containing SKILL.md, matching the dashboard ZIP importer."
    ),
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
async def export_skill_package(
    package_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    _user: User = Depends(require_permission("skill_packages")),
) -> Response:
    store = _store(server)
    locale = resolve_request_locale(request)
    row = _package_or_404(store, package_id, locale=locale)
    store.assert_can_download(row, _user)
    _assert_group_visible(server, _user, row, locale=locale)
    try:
        packed = await asyncio.to_thread(_read_package_skill_files, store, package_id)
        payload = await asyncio.to_thread(build_skills_zip, packed)
    except SkillPackageError as exc:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, str(exc)) from exc
    filename = f"{(row.name or package_id).strip() or package_id}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post("/{package_id}/skills", summary="Add a skill to a global skill package")
async def create_package_skill(
    package_id: str,
    body: CreatePackageSkillBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    store = _store(server)
    row = _package_or_404(store, package_id, locale=resolve_request_locale(request))
    store.assert_can_mutate(row, user)
    slug = _required(body.name, "name")
    if _package_skill_exists(store, package_id, slug) and not body.overwrite:
        raise HappyclawError.localized(
            ErrorCode.SKILL_ALREADY_EXISTS,
            resolve_request_locale(request),
            name=slug,
        )
    store.write_skill(
        package_id,
        slug,
        _files_from_package_skill_body(content=body.content, files=body.files),
    )
    if server.app_runtime is not None:
        await server.app_runtime.agent_registry.refresh_agents_for_package(package_id)
    return _package_skill_or_404(store, package_id, slug)


@router.put("/{package_id}/skills/{slug}", summary="Replace a global package skill")
async def update_package_skill(
    package_id: str,
    slug: str,
    body: UpdatePackageSkillBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    """Update a package skill.

    A ``content``-only body (dashboard SKILL.md editor) rewrites just the
    manifest in place so sibling files and directories are preserved. A
    ``files`` payload replaces the whole skill directory.
    """
    store = _store(server)
    row = _package_or_404(store, package_id, locale=resolve_request_locale(request))
    store.assert_can_mutate(row, user)
    _package_skill_or_404(store, package_id, slug)
    # Truthiness mirrors ``_files_from_package_skill_body`` / workspace skills.
    if body.files:
        store.write_skill(
            package_id,
            slug,
            _files_from_package_skill_body(content=body.content, files=body.files),
        )
    else:
        if not body.content:
            raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, "content or files is required")
        store.write_skill_manifest(package_id, slug, body.content)
    if server.app_runtime is not None:
        await server.app_runtime.agent_registry.refresh_agents_for_package(package_id)
    return _package_skill_or_404(store, package_id, slug)


@router.delete(
    "/{package_id}/skills/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a global package skill",
)
async def delete_package_skill(
    package_id: str,
    slug: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> None:
    store = _store(server)
    row = _package_or_404(store, package_id, locale=resolve_request_locale(request))
    store.assert_can_mutate(row, user)
    _package_skill_or_404(store, package_id, slug)
    store.delete_skill(package_id, slug)
    if server.app_runtime is not None:
        await server.app_runtime.agent_registry.refresh_agents_for_package(package_id)


def _package_has_skill(store: SkillPackageStore, package_id: str, slug: str) -> bool:
    return store.has_skill(package_id, slug)


async def _refresh_package(server: HappyclawServer, package_id: str) -> None:
    if server.app_runtime is not None:
        await server.app_runtime.agent_registry.refresh_agents_for_package(package_id)


class _PackageInstallTarget:
    """Install skills into a global skill package on disk."""

    def __init__(
        self,
        *,
        store: SkillPackageStore,
        package_id: str,
        server: HappyclawServer,
    ) -> None:
        self._store = store
        self._package_id = package_id
        self._server = server

    async def skill_exists(self, slug: str) -> bool:
        return _package_has_skill(self._store, self._package_id, slug)

    async def write_files(self, slug: str, files: list[tuple[str, bytes]]) -> None:
        self._store.write_skill(self._package_id, slug, files)

    async def after_install(self, slug: str, *, enable: bool | None = None) -> None:
        del slug, enable
        await _refresh_package(self._server, self._package_id)


@router.post(
    "/{package_id}/skills/import",
    status_code=status.HTTP_201_CREATED,
    summary="Import a skill URL into a global skill package",
)
async def import_package_skill(
    package_id: str,
    body: ImportPackageSkillBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    import asyncio  # noqa: PLC0415
    from urllib.error import HTTPError, URLError  # noqa: PLC0415

    from happyclaw.infra.skills.install import (  # noqa: PLC0415
        SkillAlreadyExistsError,
        commit_skill_install,
        resolve_url_import,
    )
    from happyclaw.infra.skills.skill_packages import SkillPackageError  # noqa: PLC0415
    from happyclaw.infra.skills.skills_hub import is_supported_skill_url  # noqa: PLC0415

    locale = resolve_request_locale(request)
    store = _store(server)
    row = _package_or_404(store, package_id, locale=locale)
    store.assert_can_mutate(row, user)

    bundle_url = body.bundle_url.strip()
    if not bundle_url:
        raise HappyclawError(ErrorCode.SLASH_BAD_ARGS, "bundle_url is required")
    if not is_supported_skill_url(bundle_url):
        raise HappyclawError.localized(ErrorCode.SKILL_IMPORT_UNSUPPORTED_URL, locale)

    target = _PackageInstallTarget(store=store, package_id=package_id, server=server)
    try:
        package = await asyncio.to_thread(
            resolve_url_import,
            bundle_url=bundle_url,
            version=body.version,
        )
        await commit_skill_install(
            target,
            package,
            overwrite=body.overwrite,
        )
    except SkillAlreadyExistsError as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_ALREADY_EXISTS,
            locale,
            name=exc.slug,
        ) from exc
    except SkillPackageError as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_IMPORT_FAILED,
            locale,
            reason=str(exc),
        ) from exc
    except ValueError as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_IMPORT_FAILED,
            locale,
            reason=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_IMPORT_FAILED,
            locale,
            reason=str(exc),
        ) from exc
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_IMPORT_FAILED,
            locale,
            reason=str(exc),
        ) from exc

    return _package_skill_or_404(store, package_id, package.slug)


@router.post(
    "/{package_id}/skills/hub/install",
    status_code=status.HTTP_201_CREATED,
    summary="Install a SkillHub skill into a global skill package",
)
async def hub_install_package_skill(
    package_id: str,
    body: HubInstallPackageSkillBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("skill_packages")),
) -> dict[str, Any]:
    from fastapi import HTTPException  # noqa: PLC0415

    from happyclaw.infra.skills.install import (  # noqa: PLC0415
        SkillAlreadyExistsError,
        install_skill_from_skillhub,
    )
    from happyclaw.infra.skills.skill_packages import (  # noqa: PLC0415
        SkillPackageError,
        SkillPackageTooLarge,
        validate_skill_slug,
    )
    from happyclaw.infra.skills.skillhub_market import (  # noqa: PLC0415
        SkillHubPackageError,
        SkillHubPackageTooLarge,
        download_skillhub_package,
        skill_market_failure_status,
    )

    locale = resolve_request_locale(request)
    store = _store(server)
    row = _package_or_404(store, package_id, locale=locale)
    store.assert_can_mutate(row, user)

    try:
        skill_name = validate_skill_slug(body.skill_name)
    except SkillPackageError:
        raise HTTPException(
            status_code=400,
            detail="skill_name is required and must not contain path separators or start with .",
        ) from None

    display_name = (body.display_name or "").strip()
    icon_url = (body.icon_url or "").strip()
    label = (
        {key: value.strip() for key, value in body.label.model_dump().items() if value}
        if body.label
        else {}
    )
    summary = (
        {key: value.strip() for key, value in body.summary.model_dump().items() if value}
        if body.summary
        else {}
    )
    if len(display_name) > 200:
        raise HTTPException(status_code=400, detail="display_name is too long")
    if any(len(value) > 200 for value in label.values()):
        raise HTTPException(status_code=400, detail="localized skill label is too long")
    if any(len(value) > 1024 for value in summary.values()):
        raise HTTPException(status_code=400, detail="localized skill summary is too long")
    if len(icon_url) > 2048 or (icon_url and not valid_skillhub_icon_url(icon_url)):
        raise HTTPException(status_code=400, detail="icon_url must be an HTTP(S) URL")

    target = _PackageInstallTarget(store=store, package_id=package_id, server=server)
    transport = "http"
    try:
        files = await download_skillhub_package(skill_name)
    except SkillHubPackageTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except SkillHubPackageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SkillHubMarketError as exc:
        raise HTTPException(
            status_code=skill_market_failure_status(exc),
            detail=str(exc),
        ) from exc

    try:
        await install_skill_from_skillhub(
            target,
            skill_name=skill_name,
            files=files,
            display_name=display_name,
            icon_url=icon_url,
            label=label,
            summary=summary,
            overwrite=body.overwrite,
        )
    except SkillAlreadyExistsError as exc:
        raise HappyclawError.localized(
            ErrorCode.SKILL_ALREADY_EXISTS,
            locale,
            name=exc.slug,
        ) from exc
    except SkillPackageTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except SkillPackageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "installed": True,
        "name": skill_name,
        "transport": transport,
        "skill": _package_skill_or_404(store, package_id, skill_name, locale=locale),
    }
