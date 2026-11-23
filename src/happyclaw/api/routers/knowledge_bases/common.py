"""Shared knowledge-base helpers: service access, payloads, group access."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import Request

from happyclaw.config import DEFAULT_MAX_UPLOAD_MB, MAX_MAX_UPLOAD_MB, upload_mb_to_bytes
from happyclaw.infra.agents.providers.onnx_catalog import (
    ONNX_PRESET_MODEL_IDS,
    list_onnx_catalog_models,
)
from happyclaw.infra.agents.providers.onnx_service import (
    OnnxServiceConfig,
    assert_catalog_model,
    is_model_downloaded,
    save_config,
)
from happyclaw.infra.errors import ErrorCode, HappyclawError
from happyclaw.infra.knowledge.files import document_path
from happyclaw.infra.knowledge.gate import assert_knowledge_usable, get_capability
from happyclaw.infra.knowledge.ocr import get_ocr_capability
from happyclaw.infra.knowledge.service import (
    MAX_BASES_PER_OWNER,
    MAX_DOCS_PER_KB,
    MAX_DOCUMENT_BYTES,
    KnowledgeService,
)
from happyclaw.infra.server import HappyclawServer
from happyclaw.infra.users.groups import RESOURCE_KNOWLEDGE_BASE, GroupAccess
from happyclaw.infra.users.identity import User
from happyclaw.infra.utils.locale import resolve_request_locale

logger = logging.getLogger(__name__)

def _kb_avatars(server: HappyclawServer) -> Any:
    assert server.services is not None
    return server.services.avatars("knowledge_base")


_TEXT_DOC_MAX_LENGTH = upload_mb_to_bytes(MAX_MAX_UPLOAD_MB)


def _knowledge_service(server: HappyclawServer) -> KnowledgeService:
    if server.services is None:
        raise HappyclawError(ErrorCode.INTERNAL_ERROR, "knowledge services are not initialized")
    return KnowledgeService(server.services)


def _row_payload(
    row: Any,
    *,
    has_original: bool | None = None,
    server: HappyclawServer | None = None,
) -> dict[str, Any]:
    payload = asdict(row)
    payload["document_id"] = row.id
    if has_original is None:
        if getattr(row, "is_dir", False):
            has_original = False
        elif server is not None:
            checker = getattr(_knowledge_service(server), "document_has_original", None)
            if callable(checker):
                has_original = checker(row)
            else:
                has_original = document_path(row.kb_id, row.id, row.filename).is_file()
        else:
            has_original = document_path(row.kb_id, row.id, row.filename).is_file()
    payload["has_original"] = bool(has_original)
    return payload


def _owner_fields(server: HappyclawServer, owner_user_id: int) -> dict[str, str | None]:
    if server.services is None:
        return {"owner_username": None, "owner_display_name": None}
    user_repo = getattr(server.services, "user_repo", None)
    if user_repo is None:
        return {"owner_username": None, "owner_display_name": None}
    owner = user_repo.get(int(owner_user_id))
    if owner is None:
        return {"owner_username": None, "owner_display_name": None}
    return {
        "owner_username": owner.username,
        "owner_display_name": owner.display_name or owner.username,
    }


def _group_access(server: HappyclawServer) -> GroupAccess | None:
    services = server.services
    repos = getattr(services, "repos", None) if services is not None else None
    if repos is None:
        return None
    return GroupAccess(repos)


def _kb_avatar_api_path(kb_id: str) -> str:
    return f"/api/knowledge-bases/{kb_id}/avatar"


def _display_kb_icon_url(server: HappyclawServer, row: Any) -> str:
    from happyclaw.infra.users.profile_avatar import profile_avatar_url  # noqa: PLC0415

    text = str(getattr(row, "icon_url", "") or "").strip()
    api = _kb_avatar_api_path(row.id)
    if text.split("?", 1)[0] == api:
        return profile_avatar_url(_kb_avatars(server), row.id, api) or api
    return text


def _base_payload(server: HappyclawServer, row: Any) -> dict[str, Any]:
    payload = asdict(row)
    payload["knowledge_base_id"] = row.id
    payload["icon_url"] = _display_kb_icon_url(server, row)
    access = _group_access(server)
    if access is not None:
        payload.update(
            access.visibility(
                RESOURCE_KNOWLEDGE_BASE,
                row.id,
                shared=bool(row.shared),
            )
        )
    return {**payload, **_owner_fields(server, row.owner_user_id)}


def _is_admin(user: User) -> bool:
    return bool(user.is_admin)


def _max_upload_mb(server: HappyclawServer) -> int:
    config = getattr(getattr(server, "services", None), "config", None)
    value = getattr(config, "max_upload_mb", None)
    if isinstance(value, int) and value > 0:
        return value
    return DEFAULT_MAX_UPLOAD_MB


def _max_upload_bytes(server: HappyclawServer) -> int:
    config = getattr(getattr(server, "services", None), "config", None)
    value = getattr(config, "max_upload_bytes", None)
    if isinstance(value, int) and value > 0:
        return value
    return MAX_DOCUMENT_BYTES


def _map_knowledge_error(
    exc: Exception, *, locale: str, server: HappyclawServer | None = None
) -> HappyclawError:
    if isinstance(exc, HappyclawError):
        return exc
    if isinstance(exc, (LookupError, FileNotFoundError)):
        return HappyclawError.localized(ErrorCode.KNOWLEDGE_NOT_FOUND, locale)
    if isinstance(exc, PermissionError):
        return HappyclawError.localized(ErrorCode.KNOWLEDGE_FORBIDDEN, locale)
    text = str(exc).lower()
    if isinstance(exc, RuntimeError):
        if "disabled" in text:
            return HappyclawError.localized(ErrorCode.KNOWLEDGE_FEATURE_DISABLED, locale)
        # Packages installed into a directory the running interpreter did not have on
        # sys.path at startup (pip's user site) are importable only after a restart.
        # Report that instead of the generic prerequisite error, which told the user
        # nothing they could act on and sent them into a retry loop.
        if "restart the server" in text:
            return HappyclawError.localized(ErrorCode.KNOWLEDGE_PREREQUISITES_RESTART_REQUIRED, locale)
        if any(
            kw in text
            for kw in (
                "prerequisite",
                "embedding",
                "ocr",
                "install",
                "component",
                "provider",
            )
        ):
            return HappyclawError.localized(ErrorCode.KNOWLEDGE_PREREQUISITES_FAILED, locale)
    if "at most 100" in text:
        return HappyclawError.localized(ErrorCode.KNOWLEDGE_DOC_LIMIT, locale)
    if "document size exceeds" in text:
        max_mb = _max_upload_mb(server) if server is not None else DEFAULT_MAX_UPLOAD_MB
        return HappyclawError.localized(
            ErrorCode.KNOWLEDGE_DOC_TOO_LARGE,
            locale,
            details={"max_mb": max_mb},
            max_mb=max_mb,
        )
    if "at most" in text and "knowledge bases" in text:
        return HappyclawError.localized(ErrorCode.KNOWLEDGE_BASE_LIMIT, locale)
    if "unsupported knowledge document content type" in text:
        return HappyclawError.localized(ErrorCode.KNOWLEDGE_UNSUPPORTED_TYPE, locale)
    if "knowledge ocr" in text:
        return HappyclawError.localized(ErrorCode.KNOWLEDGE_PREREQUISITES_FAILED, locale)
    if "unique constraint" in text or "duplicate key" in text or "already exists" in text:
        return HappyclawError.localized(ErrorCode.KNOWLEDGE_NAME_TAKEN, locale)
    if "invalid knowledge document name" in text:
        return HappyclawError.localized(ErrorCode.KNOWLEDGE_NAME_INVALID, locale)
    if "prerequisite" in text or "embedding model" in text or "embedding_model" in text:
        return HappyclawError.localized(ErrorCode.KNOWLEDGE_PREREQUISITES_FAILED, locale)
    logger.exception("unhandled error in knowledge base router: %s", exc)
    return HappyclawError.localized(
        ErrorCode.INTERNAL_ERROR,
        locale,
        details={"cause": str(exc)},
    )


def _onnx_options_for_knowledge(*, include_all: bool = False) -> list[dict[str, Any]]:
    """Recommended ONNX models, or the full catalog when *include_all* is set."""
    catalog = list_onnx_catalog_models()
    if include_all:
        models = catalog
    else:
        by_id = {str(model["id"]): model for model in catalog}
        models = [by_id[model_id] for model_id in ONNX_PRESET_MODEL_IDS if model_id in by_id]
    return [
        {
            **model,
            "downloaded": is_model_downloaded(str(model["id"])),
            "recommended": bool(model.get("recommended")),
        }
        for model in models
    ]


def _enable_onnx_service(server: HappyclawServer, model: str) -> None:
    """Turn on the local ONNX service for a downloaded catalog model."""
    assert server.services is not None
    verified = assert_catalog_model(model)
    if not is_model_downloaded(verified):
        raise RuntimeError("ONNX embedding model is not configured or not downloaded")
    save_config(
        server.services.settings_repo.set,
        OnnxServiceConfig(enabled=True, model=verified),
    )


def _require_usable(server: HappyclawServer, request: Request) -> None:
    assert server.services is not None
    try:
        assert_knowledge_usable(server.services.settings_repo.get, server.services.provider_repo)
    except (RuntimeError, ValueError) as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


def _capability_payload(server: HappyclawServer) -> dict[str, Any]:
    assert server.services is not None
    payload = get_capability(server.services.settings_repo.get, server.services.provider_repo)
    payload["ocr"] = get_ocr_capability(
        server.services.settings_repo.get, server.services.provider_repo
    )
    payload["limits"] = {
        "max_bases_per_owner": MAX_BASES_PER_OWNER,
        "max_docs_per_kb": MAX_DOCS_PER_KB,
        "max_document_bytes": _max_upload_bytes(server),
    }
    return payload
