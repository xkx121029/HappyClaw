"""Folders, documents, chunks, downloads and reindexing."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from happyclaw.api.common.content_disposition import content_disposition
from happyclaw.api.common.upload_limit import read_upload_capped
from happyclaw.api.deps import current_user, get_server, require_permission
from happyclaw.api.routers.knowledge_bases.common import (
    _is_admin,
    _knowledge_service,
    _map_knowledge_error,
    _max_upload_bytes,
    _require_usable,
    _row_payload,
)
from happyclaw.api.routers.knowledge_bases.schemas import (
    CreateFolderBody,
    CreateTextDocumentBody,
    MoveDocumentBody,
    RenameDocumentBody,
    UpdateTextDocumentBody,
)
from happyclaw.infra.errors import ErrorCode
from happyclaw.infra.knowledge.jobs import enqueue_index_document
from happyclaw.infra.server import HappyclawServer
from happyclaw.infra.users.identity import User
from happyclaw.infra.utils.locale import resolve_request_locale

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/{kb_id}/documents", summary="List knowledge-base documents")
async def list_documents(
    kb_id: str,
    request: Request,
    prefix: str | None = Query(
        default=None,
        description="When set, only immediate children of this relative folder path.",
    ),
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    try:
        return [
            _row_payload(document, server=server)
            for document in _knowledge_service(server).list_documents(
                kb_id, actor_user_id=user.id, is_admin=_is_admin(user), prefix=prefix
            )
        ]
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.post(
    "/{kb_id}/folders",
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge-base folder",
)
async def create_folder(
    kb_id: str,
    body: CreateFolderBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    try:
        folder = _knowledge_service(server).create_folder(
            kb_id, actor_user_id=user.id, path=body.path, is_admin=_is_admin(user)
        )
        return _row_payload(folder, server=server)
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.post(
    "/{kb_id}/documents/text",
    status_code=status.HTTP_201_CREATED,
    summary="Create a markdown or plain-text knowledge document",
)
async def create_text_document(
    kb_id: str,
    body: CreateTextDocumentBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    locale = resolve_request_locale(request)
    try:
        _require_usable(server, request)
        document = _knowledge_service(server).create_text_document(
            kb_id,
            actor_user_id=user.id,
            name=body.name,
            format=body.format,
            content=body.content,
            is_admin=_is_admin(user),
            path=body.path,
        )
        assert server.services is not None
        enqueue_index_document(server.services, kb_id, document.id)
        return _row_payload(document, server=server)
    except Exception as exc:
        raise _map_knowledge_error(exc, locale=locale, server=server) from exc


@router.post(
    "/{kb_id}/documents", status_code=status.HTTP_201_CREATED, summary="Upload a knowledge document"
)
async def upload_document(
    kb_id: str,
    request: Request,
    upload: UploadFile = File(
        ...,
        description="A supported text, PDF, DOC/WPS, DOCX, or PPTX document.",
    ),
    path: str | None = Form(
        default=None,
        description="Optional relative path including filename (for nested folders).",
    ),
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    locale = resolve_request_locale(request)
    try:
        _require_usable(server, request)
        content = await read_upload_capped(
            upload,
            max_bytes=_max_upload_bytes(server),
            code=ErrorCode.KNOWLEDGE_DOC_TOO_LARGE,
        )
        document = _knowledge_service(server).upload_document(
            kb_id,
            actor_user_id=user.id,
            filename=upload.filename or "",
            content_type=upload.content_type or "",
            content=content,
            is_admin=_is_admin(user),
            path=path or upload.filename or "",
        )
        assert server.services is not None
        enqueue_index_document(server.services, kb_id, document.id)
        return _row_payload(document, server=server)
    except Exception as exc:
        raise _map_knowledge_error(exc, locale=locale, server=server) from exc


@router.get(
    "/{kb_id}/documents/{doc_id}/chunks",
    summary="List indexed slices for one document",
)
async def list_document_chunks(
    kb_id: str,
    doc_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    try:
        return _knowledge_service(server).list_document_chunks(
            kb_id, doc_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.get(
    "/{kb_id}/documents/{doc_id}/preview",
    summary="Preview extracted document text",
)
async def preview_document(
    kb_id: str,
    doc_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    try:
        return _knowledge_service(server).preview_document(
            kb_id, doc_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.get(
    "/{kb_id}/documents/{doc_id}/file",
    summary="Download or inline-open the original uploaded document",
    response_class=FileResponse,
)
async def download_document_file(
    kb_id: str,
    doc_id: str,
    request: Request,
    disposition: str = Query(
        "attachment",
        pattern="^(attachment|inline)$",
        description="Content-Disposition type: attachment (download) or inline (preview).",
    ),
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(current_user),
) -> FileResponse:
    try:
        path, filename, content_type = _knowledge_service(server).resolve_document_file(
            kb_id, doc_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc
    return FileResponse(
        path=path,
        media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": content_disposition(filename, disposition=disposition)},
    )


@router.get(
    "/{kb_id}/documents/{doc_id}/content",
    summary="Read raw editable text for a markdown or plain-text document",
)
async def get_text_document(
    kb_id: str,
    doc_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    try:
        return _knowledge_service(server).read_text_document(
            kb_id, doc_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.put(
    "/{kb_id}/documents/{doc_id}/content",
    summary="Update markdown or plain-text document content and reindex",
)
async def update_text_document(
    kb_id: str,
    doc_id: str,
    body: UpdateTextDocumentBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    locale = resolve_request_locale(request)
    try:
        _require_usable(server, request)
        document = _knowledge_service(server).update_text_document(
            kb_id,
            doc_id,
            actor_user_id=user.id,
            content=body.content,
            is_admin=_is_admin(user),
        )
        assert server.services is not None
        enqueue_index_document(server.services, kb_id, doc_id)
        return _row_payload(document, server=server)
    except Exception as exc:
        raise _map_knowledge_error(exc, locale=locale, server=server) from exc


@router.post(
    "/{kb_id}/documents/{doc_id}/rename",
    summary="Rename a document or folder",
)
async def rename_document(
    kb_id: str,
    doc_id: str,
    body: RenameDocumentBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    try:
        document = _knowledge_service(server).rename_document(
            kb_id,
            doc_id,
            actor_user_id=user.id,
            new_name=body.new_name.strip(),
            is_admin=_is_admin(user),
        )
        return _row_payload(document, server=server)
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.post(
    "/{kb_id}/documents/{doc_id}/move",
    summary="Move a document or folder into another folder",
)
async def move_document(
    kb_id: str,
    doc_id: str,
    body: MoveDocumentBody,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    """Move within one knowledge base. A folder takes its contents along; nothing is reindexed."""
    try:
        document = _knowledge_service(server).move_document(
            kb_id,
            doc_id,
            actor_user_id=user.id,
            target_folder=body.target_folder,
            is_admin=_is_admin(user),
        )
        return _row_payload(document, server=server)
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.delete(
    "/{kb_id}/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
)
async def delete_document(
    kb_id: str,
    doc_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> None:
    try:
        _knowledge_service(server).delete_document(
            kb_id, doc_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.post(
    "/{kb_id}/documents/{doc_id}/reindex",
    summary="Rebuild the index for one knowledge document",
)
async def reindex_document(
    kb_id: str,
    doc_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, Any]:
    try:
        _require_usable(server, request)
        document = _knowledge_service(server).reindex_document(
            kb_id, doc_id, actor_user_id=user.id, is_admin=_is_admin(user)
        )
        assert server.services is not None
        enqueue_index_document(server.services, kb_id, doc_id)
        return _row_payload(document, server=server)
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc


@router.post("/{kb_id}/reindex", summary="Reindex all documents in a knowledge base")
async def reindex_base(
    kb_id: str,
    request: Request,
    server: HappyclawServer = Depends(get_server),
    user: User = Depends(require_permission("knowledge_bases")),
) -> dict[str, int]:
    try:
        _require_usable(server, request)
        service = _knowledge_service(server)
        service.get_writable_base(kb_id, actor_user_id=user.id, is_admin=_is_admin(user))
        documents = [
            document
            for document in service.list_documents(
                kb_id, actor_user_id=user.id, is_admin=_is_admin(user)
            )
            if not document.is_dir
        ]
        assert server.services is not None
        for document in documents:
            service.reindex_document(
                kb_id, document.id, actor_user_id=user.id, is_admin=_is_admin(user)
            )
            enqueue_index_document(server.services, kb_id, document.id)
        return {"enqueued": len(documents)}
    except Exception as exc:
        raise _map_knowledge_error(
            exc, locale=resolve_request_locale(request), server=server
        ) from exc
