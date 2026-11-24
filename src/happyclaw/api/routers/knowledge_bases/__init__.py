"""Knowledge-base HTTP API.

Split by responsibility; the package keeps the old module's namespace and
the ``/knowledge-bases`` prefix:

  feature    capability probe, embedding/OCR options, ONNX model handling
  bases      knowledge-base CRUD, avatars and default-open list
  documents  folders, text/binary documents, chunks, reindex"""

from __future__ import annotations

from fastapi import APIRouter

from happyclaw.api.routers.knowledge_bases.bases import (
    create_base,
    default_open_bases,
    delete_base,
    delete_kb_avatar,
    get_base,
    get_kb_avatar,
    list_bases,
    update_base,
    upload_kb_avatar,
)
from happyclaw.api.routers.knowledge_bases.bases import router as bases_router
from happyclaw.api.routers.knowledge_bases.common import (
    _TEXT_DOC_MAX_LENGTH,
    _base_payload,
    _capability_payload,
    _display_kb_icon_url,
    _enable_onnx_service,
    _group_access,
    _is_admin,
    _kb_avatar_api_path,
    _kb_avatars,
    _knowledge_service,
    _map_knowledge_error,
    _max_upload_bytes,
    _max_upload_mb,
    _onnx_options_for_knowledge,
    _owner_fields,
    _require_usable,
    _row_payload,
)
from happyclaw.api.routers.knowledge_bases.documents import (
    create_folder,
    create_text_document,
    delete_document,
    download_document_file,
    get_text_document,
    list_document_chunks,
    list_documents,
    move_document,
    preview_document,
    reindex_base,
    reindex_document,
    rename_document,
    update_text_document,
    upload_document,
)
from happyclaw.api.routers.knowledge_bases.documents import router as documents_router
from happyclaw.api.routers.knowledge_bases.feature import (
    activate_onnx_service,
    capability,
    embedding_options,
    ocr_options,
    onnx_download_status,
    put_feature,
    start_onnx_download,
    test_onnx_model,
)
from happyclaw.api.routers.knowledge_bases.feature import router as feature_router
from happyclaw.api.routers.knowledge_bases.schemas import (
    CreateBaseBody,
    CreateFolderBody,
    CreateTextDocumentBody,
    FeatureBody,
    MoveDocumentBody,
    OnnxDownloadBody,
    RenameDocumentBody,
    UpdateBaseBody,
    UpdateTextDocumentBody,
)

router = APIRouter()
router.include_router(feature_router, prefix="/knowledge-bases")
router.include_router(bases_router, prefix="/knowledge-bases")
router.include_router(documents_router, prefix="/knowledge-bases")

__all__ = [
    "router",
    "CreateBaseBody",
    "CreateFolderBody",
    "CreateTextDocumentBody",
    "FeatureBody",
    "MoveDocumentBody",
    "OnnxDownloadBody",
    "RenameDocumentBody",
    "UpdateBaseBody",
    "UpdateTextDocumentBody",
    "_TEXT_DOC_MAX_LENGTH",
    "_base_payload",
    "_capability_payload",
    "_display_kb_icon_url",
    "_enable_onnx_service",
    "_group_access",
    "_is_admin",
    "_kb_avatar_api_path",
    "_kb_avatars",
    "_knowledge_service",
    "_map_knowledge_error",
    "_max_upload_bytes",
    "_max_upload_mb",
    "_onnx_options_for_knowledge",
    "_owner_fields",
    "_require_usable",
    "_row_payload",
    "activate_onnx_service",
    "capability",
    "create_base",
    "create_folder",
    "create_text_document",
    "default_open_bases",
    "delete_base",
    "delete_document",
    "delete_kb_avatar",
    "download_document_file",
    "embedding_options",
    "get_base",
    "get_kb_avatar",
    "get_text_document",
    "list_bases",
    "list_document_chunks",
    "list_documents",
    "move_document",
    "ocr_options",
    "onnx_download_status",
    "preview_document",
    "put_feature",
    "reindex_base",
    "reindex_document",
    "rename_document",
    "start_onnx_download",
    "test_onnx_model",
    "update_base",
    "update_text_document",
    "upload_document",
    "upload_kb_avatar",
]
