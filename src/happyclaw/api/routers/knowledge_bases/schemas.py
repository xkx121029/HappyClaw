"""Request bodies for the knowledge-base routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from happyclaw.api.routers.knowledge_bases.common import _TEXT_DOC_MAX_LENGTH


class FeatureBody(BaseModel):
    enabled: bool = Field(description="Whether to enable the instance-wide knowledge-base feature.")
    model: str | None = Field(
        default=None,
        description="Downloaded ONNX embedding model ID; required when enabling.",
    )
    backend: str | None = Field(default=None, pattern="^(onnx|remote)$")
    provider_id: str | None = None
    ocr_enabled: bool | None = Field(
        default=None,
        description="Whether OCR is enabled for images and scanned PDFs.",
    )
    ocr_backend: str | None = Field(default=None, pattern="^(onnx|remote)$")
    ocr_model: str | None = None
    ocr_provider_id: str | None = None


class OnnxDownloadBody(BaseModel):
    model: str = Field(min_length=1, description="Catalog ONNX embedding model id to download.")


class CreateBaseBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    default_open: bool = False
    shared: bool = False
    visibility: Literal["all", "groups", "owner"] | None = None
    group_ids: list[str] | None = None
    icon_name: str = Field(default="", max_length=64)
    icon_url: str = Field(default="", max_length=2048)
    max_documents: int | None = Field(
        default=None,
        ge=0,
        le=10_000,
        description="Per-base document limit. 0 = unlimited, default 100.",
    )


class CreateFolderBody(BaseModel):
    path: str = Field(min_length=1, max_length=500, description="Relative folder path.")


class CreateTextDocumentBody(BaseModel):
    name: str = Field(
        min_length=1, max_length=200, description="File name without or with extension."
    )
    format: str = Field(pattern="^(md|txt)$", description="Text format: md or txt.")
    content: str = Field(default="", max_length=_TEXT_DOC_MAX_LENGTH)
    path: str | None = Field(
        default=None,
        max_length=500,
        description="Optional parent folder path (without filename).",
    )


class UpdateTextDocumentBody(BaseModel):
    content: str = Field(max_length=_TEXT_DOC_MAX_LENGTH)


class UpdateBaseBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    default_open: bool | None = None
    shared: bool | None = None
    visibility: Literal["all", "groups", "owner"] | None = None
    group_ids: list[str] | None = None
    icon_name: str | None = Field(default=None, max_length=64)
    icon_url: str | None = Field(default=None, max_length=2048)
    max_documents: int | None = Field(
        default=None,
        ge=0,
        le=10_000,
        description="Per-base document limit. 0 = unlimited.",
    )


class RenameDocumentBody(BaseModel):
    new_name: str = Field(min_length=1, max_length=255, description="New document or folder name.")


class MoveDocumentBody(BaseModel):
    target_folder: str = Field(
        default="",
        max_length=1024,
        description="Path of the destination folder in the same knowledge base; empty for root.",
    )
