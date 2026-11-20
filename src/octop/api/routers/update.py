"""Self-update API — mirrors finnie/octop dashboard update flow."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server, require_permission
from octop.api.routers.update_store import (
    UpgradeTaskStatus,
    cache_status,
    create_task,
    get_cached_status,
    get_task,
    update_task,
)
from octop.infra.desktop import desktop_shell_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from octop.infra.setup.release_manifest import CHANNELS, ManifestError, load_manifest
from octop.infra.setup.self_update import (
    UpgradeResult,
    fetch_pypi_info,
    get_editable_path,
    get_local_version,
    green_packages_dir,
    is_newer,
    is_prerelease,
    is_valid_version,
    parse_changelog_for_version,
    parse_version,
    run_upgrade,
    validate_upgrade_target,
)
from octop.infra.setup.service import (
    ServiceRuntime,
    build_runtime,
    detect_service_mode,
    is_service_installed,
    restart_service,
)
from octop.infra.utils.locale import DEFAULT_LOCALE, resolve_locale, resolve_request_locale

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/update", tags=["update"])

_STABLE_ONLY_KEY = "update.stable_only"
_CACHE_INTERNAL = frozenset({"latest_any", "latest_stable", "description"})

_SHELL_UPDATE_FORBIDDEN = "updates are managed by the desktop shell"


class UpdateSettingsBody(BaseModel):
    stable_only: bool = Field(..., description="When true, automatic checks ignore pre-releases")


class UpgradeBody(BaseModel):
    version: str | None = Field(
        default=None,
        description="Pin a newer release. Same/older versions are rejected before installation. "
        "Defaults to the channel latest (stable when stable_only).",
    )


class ReleaseArtifactModel(BaseModel):
    platform: str
    arch: str
    kind: str | None = None
    filename: str
    url: str
    sha256: str
    size_bytes: int


class ReleaseCheckResponse(BaseModel):
    ok: bool
    configured: bool
    current_version: str
    channel: str
    latest_version: str | None = None
    has_update: bool = False
    supported: bool = True
    minimum_supported_version: str | None = None
    release_notes: str | None = None
    published_at: str | None = None
    product: str | None = None
    artifacts: list[ReleaseArtifactModel] = Field(default_factory=list)
    source: str | None = None
    cached: bool = False
    stale: bool = False
    checked_at: str
    error_code: str | None = None
    error: str | None = None


def _read_stable_only(server: Any | None) -> bool:
    """Missing key defaults to true (only remind about stables)."""
    if server is None:
        return True
    raw = server.services.settings_repo.get(_STABLE_ONLY_KEY)
    if raw is None or not str(raw).strip():
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _channel_latest(
    latest_any: str | None,
    latest_stable: str | None,
    *,
    include_prerelease: bool,
) -> str | None:
    if include_prerelease:
        return latest_any
    if latest_stable:
        return latest_stable
    if latest_any and not is_prerelease(latest_any):
        return latest_any
    return None


def _public_status(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _CACHE_INTERNAL}


def _present_status(
    cached: dict[str, Any],
    *,
    stable_only: bool,
    include_prerelease: bool,
) -> dict[str, Any]:
    current = str(cached.get("current_version") or get_local_version())
    latest_any = cached.get("latest_any") or cached.get("latest_version")
    latest_stable = cached.get("latest_stable")
    latest = _channel_latest(latest_any, latest_stable, include_prerelease=include_prerelease)
    has_update = bool(latest and is_newer(latest, current))
    description = cached.get("description")
    notes = parse_changelog_for_version(description, latest) if has_update and latest else None
    return {
        "current_version": current,
        "latest_version": latest,
        "latest_any": latest_any,
        "latest_stable": latest_stable,
        "description": description,
        "has_update": has_update,
        "is_editable": get_editable_path() is not None,
        "service_mode": detect_service_mode(),
        "desktop": _is_desktop_process(),
        "error": cached.get("error"),
        "error_code": cached.get("error_code") if cached.get("error") else None,
        "source": cached.get("source") if latest_any is not None else None,
        "last_check_time": cached.get("last_check_time")
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "release_notes": notes,
        "stable_only": stable_only,
        "latest_is_prerelease": bool(latest and is_prerelease(latest)),
    }


def _auto_status(cached: dict[str, Any], *, stable_only: bool) -> dict[str, Any]:
    return _public_status(
        _present_status(cached, stable_only=stable_only, include_prerelease=not stable_only)
    )


def _build_status(
    *,
    latest: str | None = None,
    latest_any: str | None = None,
    latest_stable: str | None = None,
    error: str | None = None,
    error_code: str | None = None,
    source: str | None = None,
    description: str | None = None,
    stable_only: bool = True,
    include_prerelease: bool = False,
) -> dict[str, Any]:
    current = get_local_version()
    if latest_any is None:
        latest_any = latest
    if latest_any is None and error is None:
        info = fetch_pypi_info()
        if info is not None:
            latest_any = info.version
            latest_stable = info.latest_stable
            source = info.source
            description = info.description
    if latest_stable is None and latest_any and not is_prerelease(latest_any):
        latest_stable = latest_any
    payload = _present_status(
        {
            "current_version": current,
            "latest_any": latest_any,
            "latest_stable": latest_stable,
            "description": description,
            "error": error,
            "error_code": error_code,
            "source": source,
        },
        stable_only=stable_only,
        include_prerelease=include_prerelease,
    )
    cache_status(payload)
    return _public_status(payload)


def _resolve_upgrade_target(
    *,
    requested: str | None,
    latest_any: str | None,
    latest_stable: str | None,
    stable_only: bool,
) -> str | None:
    wanted = (requested or "").strip() or None
    if wanted:
        return wanted
    return _channel_latest(latest_any, latest_stable, include_prerelease=not stable_only)


@router.get("/status")
async def update_status(
    _: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Return last check result; re-probe PyPI when the server cache TTL expires."""
    if desktop_shell_enabled():
        return _desktop_shell_status()
    stable_only = _read_stable_only(server)
    cached = get_cached_status()
    if cached is not None:
        return await asyncio.to_thread(_auto_status, cached, stable_only=stable_only)
    return await asyncio.to_thread(
        _build_status,
        stable_only=stable_only,
        include_prerelease=not stable_only,
    )


@router.post("/check")
async def check_for_updates(
    _: Any = Depends(require_permission("update")),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _reject_shell_updates()
    stable_only = _read_stable_only(server)
    pypi_info = await asyncio.to_thread(fetch_pypi_info)
    if pypi_info is None:
        return await asyncio.to_thread(
            _build_status,
            latest=None,
            error="could not reach PyPI",
            error_code="pypi_unreachable",
            stable_only=stable_only,
            include_prerelease=True,
        )
    return await asyncio.to_thread(
        _build_status,
        latest_any=pypi_info.version,
        latest_stable=pypi_info.latest_stable,
        source=pypi_info.source,
        description=pypi_info.description,
        stable_only=stable_only,
        include_prerelease=True,
    )


@router.get(
    "/check",
    response_model=ReleaseCheckResponse,
    summary="Check the published release manifest",
)
async def check_release_manifest(
    response: Response,
    channel: str = Query("stable", description="Release channel: stable or beta"),
    current_version: str | None = Query(
        None,
        description="Version to compare against; defaults to the running build.",
    ),
    _: Any = Depends(current_user),
) -> ReleaseCheckResponse:
    """Read-only release check backed by the published manifest.

    The endpoint never downloads or installs anything. When the manifest source
    is unset or unreachable it still returns HTTP 200 with an ``error_code`` so
    the dashboard can explain the failure instead of showing a bare 500.
    """
    response.headers["Cache-Control"] = "private, max-age=60"

    normalized_channel = channel.strip().lower()
    if normalized_channel not in CHANNELS:
        raise HTTPException(status_code=400, detail="channel must be stable or beta")

    current = (current_version or "").strip() or get_local_version()
    if not is_valid_version(current):
        raise HTTPException(
            status_code=400, detail="current_version must be a PEP 440 version"
        )

    checked_at = datetime.now(timezone.utc).isoformat()

    def _failure(*, code: str, message: str, configured: bool) -> ReleaseCheckResponse:
        return ReleaseCheckResponse(
            ok=False,
            configured=configured,
            current_version=current,
            channel=normalized_channel,
            checked_at=checked_at,
            error_code=code,
            error=message,
        )

    try:
        snapshot = await asyncio.to_thread(load_manifest)
    except ManifestError as exc:
        return _failure(
            code=exc.code,
            message=exc.message,
            configured=exc.code != "manifest_not_configured",
        )

    manifest = snapshot.manifest
    if manifest is None:
        return _failure(
            code=snapshot.error_code or "manifest_unreachable",
            message=snapshot.error or "manifest is unavailable",
            configured=True,
        )

    if normalized_channel == "stable" and manifest.channel != "stable":
        return ReleaseCheckResponse(
            ok=False,
            configured=True,
            current_version=current,
            channel=normalized_channel,
            has_update=False,
            source=snapshot.source,
            cached=snapshot.cached,
            stale=snapshot.stale,
            checked_at=checked_at,
            error_code="no_release_for_channel",
            error=f"the published manifest is on the {manifest.channel} channel",
        )

    supported = True
    if manifest.minimum_supported_version:
        supported = not is_newer(manifest.minimum_supported_version, current)

    return ReleaseCheckResponse(
        ok=True,
        configured=True,
        current_version=current,
        channel=normalized_channel,
        latest_version=manifest.version,
        has_update=is_newer(manifest.version, current),
        supported=supported,
        minimum_supported_version=manifest.minimum_supported_version,
        release_notes=manifest.notes,
        published_at=manifest.published_at,
        product=manifest.product,
        artifacts=[
            ReleaseArtifactModel(
                platform=artifact.platform,
                arch=artifact.arch,
                kind=artifact.kind,
                filename=artifact.filename,
                url=artifact.url,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
            )
            for artifact in manifest.artifacts
        ],
        source=snapshot.source,
        cached=snapshot.cached,
        stale=snapshot.stale,
        checked_at=checked_at,
        error_code=snapshot.error_code,
        error=snapshot.error,
    )


@router.patch("/settings")
async def update_settings(
    body: UpdateSettingsBody,
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("update")),
) -> dict[str, Any]:
    """Persist whether automatic checks should ignore pre-release versions."""
    _reject_shell_updates()
    server.services.settings_repo.set(_STABLE_ONLY_KEY, "true" if body.stable_only else "false")
    cached = get_cached_status()
    if cached is None:
        return await asyncio.to_thread(
            _build_status,
            stable_only=body.stable_only,
            include_prerelease=not body.stable_only,
        )
    remapped = await asyncio.to_thread(
        _present_status,
        cached,
        stable_only=body.stable_only,
        include_prerelease=not body.stable_only,
    )
    cache_status(remapped)
    return _public_status(remapped)


async def _upgrade_worker(
    task_id: str,
    *,
    allow_prerelease: bool = False,
    version: str | None = None,
    locale: str = DEFAULT_LOCALE,
) -> None:
    await update_task(task_id, stage="downloading", percent=20)
    upgrade_task = asyncio.create_task(
        asyncio.to_thread(
            run_upgrade,
            verbose=False,
            allow_prerelease=allow_prerelease,
            version=version,
            locale=locale,
        )
    )
    percent = 20
    try:
        while True:
            try:
                result: UpgradeResult = await asyncio.wait_for(
                    asyncio.shield(upgrade_task),
                    timeout=5,
                )
                break
            except TimeoutError:
                percent = min(percent + 5, 85)
                await update_task(task_id, stage="installing", percent=percent)
    except Exception as exc:
        logger.exception("upgrade task %s failed unexpectedly", task_id)
        await update_task(
            task_id,
            status=UpgradeTaskStatus.ERROR,
            stage="error",
            percent=None,
            success=False,
            error=str(exc) or type(exc).__name__,
        )
        return
    mirror_errors = result.mirror_errors or None
    if not result.success:
        await update_task(
            task_id,
            status=UpgradeTaskStatus.ERROR,
            stage="error",
            percent=None,
            success=False,
            error=result.error or "upgrade failed",
            mirror_errors=mirror_errors,
        )
        return
    new_version = result.installed_version or version
    await update_task(
        task_id,
        status=UpgradeTaskStatus.COMPLETE,
        stage="complete",
        percent=100,
        new_version=new_version,
        success=True,
        error=None,
        mirror_errors=mirror_errors,
    )


@router.post("/upgrade", summary="Upgrade HappyClaw")
async def trigger_upgrade(
    request: Request,
    body: UpgradeBody = Body(default_factory=UpgradeBody),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("update")),
) -> dict[str, Any]:
    _reject_shell_updates()
    if get_editable_path() is not None:
        raise OctopError(
            ErrorCode.FORBIDDEN,
            "editable installs must be upgraded manually (git pull / uv sync)",
        )
    stable_only = _read_stable_only(server)
    info = await asyncio.to_thread(fetch_pypi_info)
    requested = body.version if body is not None else None
    target = _resolve_upgrade_target(
        requested=requested,
        latest_any=info.version if info else None,
        latest_stable=info.latest_stable if info else None,
        stable_only=stable_only,
    )
    validate_upgrade_target(target, await asyncio.to_thread(get_local_version))
    allow_prerelease = bool(target and is_prerelease(target))
    task = await create_task()
    asyncio.create_task(
        _upgrade_worker(
            task.task_id,
            allow_prerelease=allow_prerelease,
            version=target,
            locale=resolve_locale(
                user_locale=getattr(_, "locale", None),
                explicit=resolve_request_locale(request),
            ),
        )
    )
    return {"task_id": task.task_id, "status": "started"}


@router.get("/progress")
async def upgrade_progress(
    task_id: str = Query(...),
    _: Any = Depends(require_permission("update")),
) -> dict[str, Any]:
    task = await get_task(task_id)
    if task is None:
        raise OctopError(ErrorCode.NOT_FOUND, "upgrade task not found")
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "stage": task.stage,
        "percent": task.percent,
        "new_version": task.new_version,
        "success": task.success,
        "error": task.error,
        "mirror_errors": task.mirror_errors,
    }


def _is_desktop_process() -> bool:
    if green_packages_dir() is not None:
        return True
    raw = (os.environ.get("OCTOP_DESKTOP") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _reject_shell_updates() -> None:
    """Reject self-update requests when the Electron shell owns this process."""
    if desktop_shell_enabled():
        raise OctopError(ErrorCode.FORBIDDEN, _SHELL_UPDATE_FORBIDDEN)


def _desktop_shell_status() -> dict[str, Any]:
    """Status payload for the desktop-hosted process: no PyPI probing, ever."""
    return {
        "current_version": get_local_version(),
        "latest_version": None,
        "latest_any": None,
        "latest_stable": None,
        "description": None,
        "has_update": False,
        "is_editable": get_editable_path() is not None,
        "service_mode": detect_service_mode(),
        "desktop": True,
        "updates_managed_by_shell": True,
        "error": None,
        "error_code": None,
        "source": None,
        "last_check_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "release_notes": None,
        "stable_only": True,
        "latest_is_prerelease": False,
    }


def _restart_desktop_process(server: OctopServer) -> None:
    time.sleep(0.4)

    # Flush SQLite WAL before replacing the process image, otherwise uncheckpointed
    # writes (common in WAL mode) are lost when the connection FD is closed by execv.
    if server.services is not None and getattr(server.services.db, "dialect", None) == "sqlite":
        try:
            with server.services.db.connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            server.services.db.close()
        except Exception:
            logger.exception("failed to checkpoint/close database before desktop restart")

    argv = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])
    os.execv(argv[0], argv)


def _restart_service_task(runtime: ServiceRuntime) -> None:
    try:
        restart_service(runtime)
    except Exception:
        logger.exception("background service restart failed")


@router.post("/restart")
async def restart_service_endpoint(
    background_tasks: BackgroundTasks,
    server: OctopServer = Depends(get_server),
    _: Any = Depends(require_permission("update")),
) -> dict[str, Any]:
    if desktop_shell_enabled():
        raise OctopError(ErrorCode.FORBIDDEN, _SHELL_UPDATE_FORBIDDEN)
    if _is_desktop_process():
        background_tasks.add_task(_restart_desktop_process, server)
        return {"status": "restarting", "service_mode": "desktop"}
    mode = detect_service_mode()
    if mode is None:
        raise OctopError(
            ErrorCode.FORBIDDEN,
            "service restart is only available when OCTOP_SERVICE_MODE is set",
        )
    try:
        runtime = build_runtime(mode=mode)
        if not is_service_installed(
            runtime.mode,
            scope=runtime.scope,
            run_as_user=runtime.run_as_user,
        ):
            raise RuntimeError(
                f"octop system service is not installed (expected unit for mode={runtime.mode})"
            )
    except RuntimeError as exc:
        raise OctopError(ErrorCode.INTERNAL_ERROR, str(exc)) from exc
    except Exception as exc:
        raise OctopError(ErrorCode.INTERNAL_ERROR, str(exc)) from exc
    background_tasks.add_task(_restart_service_task, runtime)
    return {"status": "restarting", "service_mode": mode}
