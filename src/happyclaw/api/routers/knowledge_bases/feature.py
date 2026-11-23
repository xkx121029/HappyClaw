"""Feature capability, embedding/OCR options and local ONNX model handling."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from happyclaw.api.deps import current_user, get_server, require_permission
from happyclaw.api.routers.knowledge_bases.common import (
    _capability_payload,
    _enable_onnx_service,
    _map_knowledge_error,
    _onnx_options_for_knowledge,
)
from happyclaw.api.routers.knowledge_bases.schemas import FeatureBody, OnnxDownloadBody
from happyclaw.infra.agents.providers.model_flags import (
    is_chat_eligible_model,
    is_embedding_model,
    is_onnx_local_provider,
    is_vision_model,
)
from happyclaw.infra.agents.providers.onnx_service import (
    DOWNLOAD_MANAGER,
    ensure_local_embedding_deps_async,
    probe_local_model,
    status_payload,
)
from happyclaw.infra.knowledge.gate import get_capability, set_feature_enabled
from happyclaw.infra.knowledge.jobs import reindex_all_documents
from happyclaw.infra.knowledge.ocr import (
    ensure_ocr_deps_async,
    get_ocr_capability,
    set_ocr_settings,
    validate_ocr_settings,
)
from happyclaw.infra.server import HappyclawServer
from happyclaw.infra.users.identity import User
from happyclaw.infra.utils.locale import resolve_request_locale

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/capability", summary="Get knowledge-base feature capability")
async def capability(
    server: HappyclawServer = Depends(get_server),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    return _capability_payload(server)


@router.get("/embedding-options", summary="List knowledge embedding backend options")
async def embedding_options(
    all_onnx: bool = Query(
        False,
        description="Include the full local ONNX catalog instead of the three recommended models",
    ),
    server: HappyclawServer = Depends(get_server),
    _admin: User = Depends(require_permission("knowledge_settings")),
) -> dict[str, Any]:
    assert server.services is not None
    remote = []
    for provider in server.services.provider_repo.list_all():
        if is_onnx_local_provider(
            provider.name, provider_api_key=getattr(provider, "api_key", None)
        ):
            continue
        models = [
            {"id": str(model["id"]), "name": str(model.get("name") or model["id"])}
            for model in provider.get_models()
            if str(model.get("id") or "").strip()
            and is_embedding_model(
                model,
                provider_name=provider.name,
                provider_api_key=getattr(provider, "api_key", None),
            )
        ]
        if models:
            remote.append(
                {"provider_id": str(provider.id), "provider_name": provider.name, "models": models}
            )
    return {
        "onnx": _onnx_options_for_knowledge(include_all=all_onnx is True),
        "remote": remote,
    }


@router.get("/ocr-options", summary="List knowledge OCR backend options")
async def ocr_options(
    server: HappyclawServer = Depends(get_server),
    _admin: User = Depends(require_permission("knowledge_settings")),
) -> dict[str, Any]:
    assert server.services is not None
    remote = []
    for provider in server.services.provider_repo.list_all():
        if not provider.enabled or not provider.api_key or not provider.base_url:
            continue
        models = [
            {"id": str(model["id"]), "name": str(model.get("name") or model["id"])}
            for model in provider.get_models()
            if str(model.get("id") or "").strip()
            and is_chat_eligible_model(
                model,
                provider_name=provider.name,
                provider_api_key=provider.api_key,
            )
            and is_vision_model(model)
        ]
        if models:
            remote.append(
                {"provider_id": str(provider.id), "provider_name": provider.name, "models": models}
            )
    return {
        "local": {"id": "rapidocr", "name": "RapidOCR (ONNX)"},
        "remote": remote,
    }


@router.put("/feature", summary="Enable or disable knowledge bases")
async def put_feature(
    body: FeatureBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    _admin: User = Depends(require_permission("knowledge_settings")),
) -> dict[str, Any]:
    assert server.services is not None
    previous = get_capability(server.services.settings_repo.get, server.services.provider_repo)
    previous_ocr = get_ocr_capability(
        server.services.settings_repo.get, server.services.provider_repo
    )
    selected_backend = (body.backend or "onnx").strip().lower()
    if body.enabled and selected_backend == "onnx":
        try:
            await ensure_local_embedding_deps_async(allow_install=True)
        except RuntimeError as exc:
            raise _map_knowledge_error(
                exc, locale=resolve_request_locale(request), server=server
            ) from exc
    if body.ocr_enabled:
        try:
            await ensure_ocr_deps_async(backend=(body.ocr_backend or "onnx").strip().lower())
            validate_ocr_settings(
                enabled=True,
                backend=body.ocr_backend,
                model=body.ocr_model,
                provider_id=body.ocr_provider_id,
                provider_repo=server.services.provider_repo,
            )
        except RuntimeError as exc:
            raise _map_knowledge_error(
                exc, locale=resolve_request_locale(request), server=server
            ) from exc
        except ValueError as exc:
            raise _map_knowledge_error(
                exc, locale=resolve_request_locale(request), server=server
            ) from exc
    try:
        set_feature_enabled(
            server.services.settings_repo.get,
            server.services.settings_repo.set,
            enabled=body.enabled,
            backend=body.backend,
            model=body.model,
            provider_id=body.provider_id,
            provider_repo=server.services.provider_repo,
        )
        if body.ocr_enabled is not None:
            set_ocr_settings(
                server.services.settings_repo.set,
                enabled=body.ocr_enabled,
                backend=body.ocr_backend,
                model=body.ocr_model,
                provider_id=body.ocr_provider_id,
                provider_repo=server.services.provider_repo,
            )
    except (RuntimeError, ValueError) as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc
    capability = _capability_payload(server)
    if body.enabled and selected_backend == "onnx":
        selected_model = str(capability.get("selected_model") or "").strip()
        if selected_model:
            with suppress(RuntimeError, ValueError):
                _enable_onnx_service(server, selected_model)
    ocr_changed = any(
        previous_ocr.get(key) != capability["ocr"].get(key)
        for key in ("enabled", "backend", "model", "provider_id")
    )
    if body.enabled and (
        not previous["feature_enabled"]
        or previous["selected_model"] != capability["selected_model"]
        or previous["backend"] != capability["backend"]
        or previous["provider_id"] != capability["provider_id"]
        or ocr_changed
    ):
        reindex_all_documents(server.services, capability["selected_model"])
    return capability


@router.post("/onnx-download", summary="Download a local ONNX embedding model")
async def start_onnx_download(
    body: OnnxDownloadBody,
    request: Request,
    _: User = Depends(require_permission("knowledge_settings")),
) -> dict[str, Any]:
    try:
        state = await DOWNLOAD_MANAGER.start_download(body.model.strip())
    except (RuntimeError, ValueError) as exc:
        raise _map_knowledge_error(exc, locale=resolve_request_locale(request)) from exc
    return state.to_dict()


@router.get("/onnx-download-status", summary="Poll ONNX embedding model download progress")
async def onnx_download_status(
    _: User = Depends(require_permission("knowledge_settings")),
) -> dict[str, Any]:
    return DOWNLOAD_MANAGER.state.to_dict()


@router.post("/onnx-activate", summary="Enable local ONNX service for a downloaded model")
async def activate_onnx_service(
    body: OnnxDownloadBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    _: User = Depends(require_permission("knowledge_settings")),
) -> dict[str, Any]:
    try:
        await ensure_local_embedding_deps_async(allow_install=True)
        _enable_onnx_service(server, body.model.strip())
    except (RuntimeError, ValueError) as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc
    assert server.services is not None
    return status_payload(server.services.settings_repo.get, DOWNLOAD_MANAGER.state)


@router.post("/onnx-test", summary="Probe the selected local ONNX embedding model")
async def test_onnx_model(
    body: OnnxDownloadBody,
    _: User = Depends(require_permission("knowledge_settings")),
) -> dict[str, Any]:
    """Verify the model actually embeds, on-device.

    Mirrors ``/onnx-models/test`` for the knowledge-settings role: that one is
    gated on ``onnx_models``, which a knowledge-settings admin need not hold.
    """
    return await probe_local_model(body.model.strip())
