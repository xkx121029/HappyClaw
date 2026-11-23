import type { App } from "antd";
import type { TFunction } from "i18next";
import type { MutableRefObject } from "react";
import { useEffect, useRef, useState } from "react";

import {
  knowledgeBasesApi,
  DEFAULT_KNOWLEDGE_LIMITS,
  type KnowledgeBase,
  type KnowledgeCapability,
  type KnowledgeDocument,
} from "../../../api/modules/knowledgeBases";
import type { TextDocumentFormat } from "../TextDocumentEditorModal";
import { apiErrorMessage } from "../../../utils/apiError";
import {
  joinKnowledgePath,
  KNOWLEDGE_DOC_TREE_ROOT,
  knowledgeBasename,
  knowledgeFileNameParts,
} from "../knowledgeFolder";
import {
  BASE_DOCUMENT_TYPES,
  OCR_DOCUMENT_TYPES,
  fileMatchesAccept,
} from "../knowledgeFileTypes";
import {
  isKnowledgeDocumentLimitReached,
  knowledgeDocumentCap,
} from "../knowledgeLimits";

type AppApi = ReturnType<typeof App.useApp>;

export interface UseKnowledgeEntriesArgs {
  t: TFunction;
  message: AppApi["message"];
  selected: KnowledgeBase | null;
  selectedIdRef: MutableRefObject<string | null>;
  documents: KnowledgeDocument[];
  loadDetail: (id: string, options?: { silent?: boolean }) => Promise<void>;
  loadBases: () => Promise<void>;
  capability: KnowledgeCapability | null;
  onRenamePreview: (documentId: string, nextName: string) => void;
}

/** Folder navigation plus folder/file create, rename, move, delete and upload. */
export function useKnowledgeEntries({
  t,
  message,
  selected,
  selectedIdRef,
  documents,
  loadDetail,
  loadBases,
  capability,
  onRenamePreview,
}: UseKnowledgeEntriesArgs) {
  const usable = Boolean(capability?.usable);
  const supportedDocumentTypes = capability?.ocr?.usable
    ? `${BASE_DOCUMENT_TYPES},${OCR_DOCUMENT_TYPES}`
    : BASE_DOCUMENT_TYPES;
  const limits = capability?.limits ?? DEFAULT_KNOWLEDGE_LIMITS;
  const fileCount = documents.filter((document) => !document.is_dir).length;
  const documentCap = knowledgeDocumentCap(
    selected?.max_documents,
    limits.max_docs_per_kb,
  );
  const isAtDocumentLimit = isKnowledgeDocumentLimitReached(
    fileCount,
    documentCap,
  );


  const [currentFolder, setCurrentFolder] = useState("");
  const [docTreeExpanded, setDocTreeExpanded] = useState<string[]>([
    KNOWLEDGE_DOC_TREE_ROOT,
  ]);
  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [renameModalOpen, setRenameModalOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<KnowledgeDocument | null>(
    null,
  );
  const [renameName, setRenameName] = useState("");
  const [moveTarget, setMoveTarget] = useState<KnowledgeDocument | null>(null);
  const [moveDestination, setMoveDestination] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);

  const [textEditorOpen, setTextEditorOpen] = useState(false);
  const [textEditorMode, setTextEditorMode] = useState<"create" | "edit">(
    "create",
  );
  const [textEditorLoading, setTextEditorLoading] = useState(false);
  const [textEditorSaving, setTextEditorSaving] = useState(false);
  const [textEditorDocId, setTextEditorDocId] = useState<string | null>(null);
  const [textEditorName, setTextEditorName] = useState("");
  const [textEditorFormat, setTextEditorFormat] =
    useState<TextDocumentFormat>("md");
  const [textEditorContent, setTextEditorContent] = useState("");

  const [uploadState, setUploadState] = useState<{
    baseId: string;
    filename: string;
    index: number;
    total: number;
    percent: number;
  } | null>(null);
  const uploadInFlightRef = useRef(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  const dragDepthRef = useRef(0);
  const [dragActive, setDragActive] = useState(false);

  const uploadDocuments = async (files: FileList | File[] | null) => {
    if (!selected || !files || !usable || isAtDocumentLimit) return;
    if (uploadInFlightRef.current) return;
    const baseId = selected.id;
    const remaining =
      documentCap === null
        ? Number.POSITIVE_INFINITY
        : Math.max(0, documentCap - fileCount);
    const incoming = Array.from(files);
    const matched = incoming.filter((file) =>
      fileMatchesAccept(file, supportedDocumentTypes),
    );
    const skippedType = incoming.length - matched.length;
    if (skippedType > 0) {
      message.warning(
        t("knowledgeBases.dropUploadUnsupported", { count: skippedType }),
      );
    }
    const chosen = matched.slice(0, remaining);
    if (chosen.length === 0) return;
    if (documentCap !== null && matched.length > remaining) {
      message.warning(
        t("knowledgeBases.documentLimitReached", {
          count: documentCap,
        }),
      );
    }
    const oversized = chosen.filter(
      (file) => file.size > limits.max_document_bytes,
    );
    if (oversized.length > 0) {
      message.error(
        t("knowledgeBases.documentTooLarge", {
          sizeMb: Math.round(limits.max_document_bytes / (1024 * 1024)),
        }),
      );
      if (uploadRef.current) uploadRef.current.value = "";
      return;
    }
    uploadInFlightRef.current = true;
    try {
      for (const [index, file] of chosen.entries()) {
        setUploadState({
          baseId,
          filename: file.name,
          index: index + 1,
          total: chosen.length,
          percent: 0,
        });
        await knowledgeBasesApi.uploadDocument(
          baseId,
          file,
          joinKnowledgePath(currentFolder, file.name),
          (percent) =>
            setUploadState((current) =>
              current &&
              current.baseId === baseId &&
              current.filename === file.name
                ? { ...current, percent }
                : current,
            ),
        );
        // Show each finished file while the remaining ones still upload.
        // Skip when the user has opened another base — loadDetail would
        // replace that view with this upload's base.
        if (index < chosen.length - 1 && selectedIdRef.current === baseId) {
          void loadDetail(baseId, { silent: true });
        }
      }
      if (selectedIdRef.current === baseId) {
        await loadDetail(baseId);
      }
      await loadBases();
      message.success(t("knowledgeBases.uploaded"));
    } catch (error) {
      message.error(
        apiErrorMessage(error, t("knowledgeBases.uploadFailed"), t),
      );
    } finally {
      uploadInFlightRef.current = false;
      setUploadState((current) =>
        current?.baseId === baseId ? null : current,
      );
      if (uploadRef.current) uploadRef.current.value = "";
    }
  };

  const resetDragActive = () => {
    dragDepthRef.current = 0;
    setDragActive(false);
  };

  const createFolder = async () => {
    if (!selected) return;
    const name = folderName.trim();
    if (!name) return;
    try {
      await knowledgeBasesApi.createFolder(
        selected.id,
        joinKnowledgePath(currentFolder, name),
      );
      setFolderModalOpen(false);
      setFolderName("");
      await loadDetail(selected.id, { silent: true });
    } catch (error) {
      message.error(
        apiErrorMessage(error, t("knowledgeBases.createFolderFailed"), t),
      );
    }
  };

  const openRenameFolder = (document: KnowledgeDocument) => {
    setRenameTarget(document);
    setRenameName(knowledgeBasename(document.path || document.filename));
    setRenameModalOpen(true);
  };

  const openRenameFile = (document: KnowledgeDocument) => {
    const current = knowledgeBasename(document.path || document.filename);
    setRenameTarget(document);
    setRenameName(knowledgeFileNameParts(current).stem);
    setRenameModalOpen(true);
  };

  const renameEntry = async () => {
    if (!selected || !renameTarget) return;
    const trimmed = renameName.trim();
    if (!trimmed) return;
    const current = knowledgeBasename(
      renameTarget.path || renameTarget.filename,
    );
    const next = renameTarget.is_dir
      ? trimmed
      : `${trimmed}${knowledgeFileNameParts(current).suffix}`;
    if (next === current) {
      setRenameModalOpen(false);
      return;
    }
    const renamingFile = !renameTarget.is_dir;
    try {
      await knowledgeBasesApi.renameDocument(
        selected.id,
        renameTarget.id,
        next,
      );
      setRenameModalOpen(false);
      setRenameTarget(null);
      setRenameName("");
      onRenamePreview(renameTarget.id, next);
      await loadDetail(selected.id);
      message.success(
        t(
          renamingFile
            ? "knowledgeBases.renameFileSuccess"
            : "knowledgeBases.renameFolderSuccess",
        ),
      );
    } catch (error) {
      message.error(
        apiErrorMessage(
          error,
          t(
            renamingFile
              ? "knowledgeBases.renameFileFailed"
              : "knowledgeBases.renameFolderFailed",
          ),
          t,
        ),
      );
    }
  };

  const openMoveEntry = (document: KnowledgeDocument) => {
    setMoveTarget(document);
    setMoveDestination(null);
  };

  const moveEntry = async () => {
    if (!selected || !moveTarget || moveDestination === null) return;
    setMoving(true);
    try {
      await knowledgeBasesApi.moveDocument(
        selected.id,
        moveTarget.id,
        moveDestination,
      );
      setMoveTarget(null);
      await loadDetail(selected.id);
      message.success(t("knowledgeBases.moveSuccess"));
    } catch (error) {
      message.error(apiErrorMessage(error, t("knowledgeBases.moveFailed"), t));
    } finally {
      setMoving(false);
    }
  };

  const deleteDocument = async (documentId: string) => {
    if (!selected) return;
    try {
      await knowledgeBasesApi.deleteDocument(selected.id, documentId);
      await loadDetail(selected.id);
      await loadBases();
    } catch (error) {
      message.error(
        apiErrorMessage(error, t("knowledgeBases.deleteFailed"), t),
      );
    }
  };

  const rebuildDocument = async (documentId: string) => {
    if (!selected) return;
    try {
      await knowledgeBasesApi.reindexDocument(selected.id, documentId);
      message.success(t("knowledgeBases.rebuildDocumentSuccess"));
      await loadDetail(selected.id);
    } catch (error) {
      message.error(
        apiErrorMessage(error, t("knowledgeBases.rebuildDocumentFailed"), t),
      );
    }
  };

  const openCreateTextDocument = () => {
    setTextEditorMode("create");
    setTextEditorDocId(null);
    setTextEditorName("");
    setTextEditorFormat("md");
    setTextEditorContent("");
    setTextEditorLoading(false);
    setTextEditorOpen(true);
  };

  const openEditTextDocument = async (document: KnowledgeDocument) => {
    if (!selected) return;
    setTextEditorMode("edit");
    setTextEditorDocId(document.id);
    setTextEditorName(document.filename);
    setTextEditorFormat(
      document.filename.toLowerCase().endsWith(".txt") ||
        document.content_type === "text/plain"
        ? "txt"
        : "md",
    );
    setTextEditorContent("");
    setTextEditorOpen(true);
    setTextEditorLoading(true);
    try {
      const payload = await knowledgeBasesApi.getTextDocument(
        selected.id,
        document.id,
      );
      setTextEditorContent(payload.text);
      setTextEditorName(payload.filename);
      setTextEditorFormat(
        payload.content_type === "text/plain" ||
          payload.filename.toLowerCase().endsWith(".txt")
          ? "txt"
          : "md",
      );
    } catch (error) {
      setTextEditorOpen(false);
      message.error(
        apiErrorMessage(error, t("knowledgeBases.editDocumentFailed"), t),
      );
    } finally {
      setTextEditorLoading(false);
    }
  };

  const saveTextDocument = async (values: {
    name: string;
    format: TextDocumentFormat;
    content: string;
  }) => {
    if (!selected) return;
    setTextEditorSaving(true);
    try {
      if (textEditorMode === "create") {
        await knowledgeBasesApi.createTextDocument(selected.id, {
          name: values.name,
          format: values.format,
          content: values.content,
          path: currentFolder || undefined,
        });
        message.success(t("knowledgeBases.createFileSuccess"));
      } else if (textEditorDocId) {
        await knowledgeBasesApi.updateTextDocument(
          selected.id,
          textEditorDocId,
          values.content,
        );
        message.success(t("knowledgeBases.editDocumentSuccess"));
      }
      setTextEditorOpen(false);
      await loadDetail(selected.id);
    } catch (error) {
      message.error(
        apiErrorMessage(
          error,
          textEditorMode === "create"
            ? t("knowledgeBases.createFileFailed")
            : t("knowledgeBases.editDocumentFailed"),
          t,
        ),
      );
    } finally {
      setTextEditorSaving(false);
    }
  };
  useEffect(() => {
    setCurrentFolder("");
    setDocTreeExpanded([KNOWLEDGE_DOC_TREE_ROOT]);
  }, [selected?.id]);

  useEffect(() => {
    setDocTreeExpanded((prev) => {
      const keys = new Set(prev);
      keys.add(KNOWLEDGE_DOC_TREE_ROOT);
      let acc = "";
      for (const part of currentFolder.split("/").filter(Boolean)) {
        acc = acc ? `${acc}/${part}` : part;
        keys.add(acc);
      }
      const next = [...keys];
      if (next.every((key) => prev.includes(key))) return prev;
      return next;
    });
  }, [currentFolder]);

  return {
    currentFolder,
    setCurrentFolder,
    docTreeExpanded,
    setDocTreeExpanded,
    folderModalOpen,
    setFolderModalOpen,
    folderName,
    setFolderName,
    renameModalOpen,
    setRenameModalOpen,
    renameTarget,
    renameName,
    setRenameName,
    moveTarget,
    setMoveTarget,
    moveDestination,
    setMoveDestination,
    moving,
    dragDepthRef,
    uploadState,
    uploadRef,
    dragActive,
    setDragActive,
    textEditorOpen,
    setTextEditorOpen,
    textEditorMode,
    textEditorLoading,
    textEditorSaving,
    textEditorName,
    textEditorFormat,
    textEditorContent,
    uploadDocuments,
    resetDragActive,
    createFolder,
    openRenameFolder,
    openRenameFile,
    renameEntry,
    openMoveEntry,
    moveEntry,
    deleteDocument,
    rebuildDocument,
    openCreateTextDocument,
    openEditTextDocument,
    saveTextDocument,
  };
}
