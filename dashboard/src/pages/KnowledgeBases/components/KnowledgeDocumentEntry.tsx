import { Button, Popconfirm, Tooltip } from "antd";
import {
  Download,
  Eye,
  FolderInput,
  Pencil,
  PencilLine,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";

import type { KnowledgeDocument } from "../../../api/modules/knowledgeBases";
import {
  canDownloadKnowledgeOriginal,
  canPreviewKnowledgeDocument,
  isEditableKnowledgeDocument,
} from "../../../utils/knowledgeDocPreview";
import { knowledgeBasename } from "../knowledgeFolder";
import { fileExtensionLabel } from "../knowledgeFileTypes";
import styles from "../index.module.less";

export interface KnowledgeDocumentActionsProps {
  document: KnowledgeDocument;
  canWriteSelected: boolean;
  openDocumentPreview: (
    document: KnowledgeDocument,
    mode?: "file" | "chunks",
  ) => Promise<void>;
  downloadDocumentOriginal: (
    documentId: string,
    filename: string,
  ) => Promise<void>;
  openEditTextDocument: (document: KnowledgeDocument) => Promise<void>;
  rebuildDocument: (documentId: string) => Promise<void>;
  openRenameFolder: (document: KnowledgeDocument) => void;
  openMoveEntry: (document: KnowledgeDocument) => void;
  deleteDocument: (documentId: string) => Promise<void>;
}

export function KnowledgeDocumentActions({
  document,
  canWriteSelected,
  openDocumentPreview,
  downloadDocumentOriginal,
  openEditTextDocument,
  rebuildDocument,
  openRenameFolder,
  openMoveEntry,
  deleteDocument,
}: KnowledgeDocumentActionsProps) {
  const { t } = useTranslation();
  const canPreview = canPreviewKnowledgeDocument(document);
  const previewBtn = (
    <Button
      type="text"
      size="small"
      icon={<Eye size={14} />}
      disabled={!canPreview}
      aria-label={t("knowledgeBases.previewDocument")}
      onClick={() => void openDocumentPreview(document)}
    />
  );
  return (
    <div
      className={styles.docCardActions}
      data-kb-doc-actions=""
      onClick={(event) => event.stopPropagation()}
    >
      {document.is_dir ? null : (
        <>
          <Tooltip
            title={
              canPreview
                ? t("knowledgeBases.previewDocument")
                : t("knowledgeBases.previewUnsupported")
            }
          >
            {canPreview ? previewBtn : <span>{previewBtn}</span>}
          </Tooltip>
          {canDownloadKnowledgeOriginal(document) ? (
            <Tooltip title={t("knowledgeBases.downloadOriginal")}>
              <Button
                type="text"
                size="small"
                icon={<Download size={14} />}
                aria-label={t("knowledgeBases.downloadOriginal")}
                onClick={() =>
                  void downloadDocumentOriginal(
                    document.id,
                    document.filename,
                  )
                }
              />
            </Tooltip>
          ) : null}
        </>
      )}
      {canWriteSelected ? (
        <>
          {!document.is_dir && isEditableKnowledgeDocument(document) ? (
            <Tooltip title={t("knowledgeBases.editDocument")}>
              <Button
                type="text"
                size="small"
                icon={<Pencil size={14} />}
                aria-label={t("knowledgeBases.editDocument")}
                onClick={() => void openEditTextDocument(document)}
              />
            </Tooltip>
          ) : null}
          {document.is_dir ? null : (
            <Popconfirm
              title={t("knowledgeBases.rebuildDocumentConfirm")}
              onConfirm={() => void rebuildDocument(document.id)}
            >
              <Tooltip title={t("knowledgeBases.rebuildDocument")}>
                <Button
                  type="text"
                  size="small"
                  icon={<RefreshCw size={14} />}
                  aria-label={t("knowledgeBases.rebuildDocument")}
                />
              </Tooltip>
            </Popconfirm>
          )}
          {document.is_dir ? (
            <Tooltip title={t("knowledgeBases.renameFolder")}>
              <Button
                type="text"
                size="small"
                icon={<PencilLine size={14} />}
                aria-label={t("knowledgeBases.renameFolder")}
                onClick={(event) => {
                  event.stopPropagation();
                  openRenameFolder(document);
                }}
              />
            </Tooltip>
          ) : null}
          <Tooltip title={t("knowledgeBases.moveEntry")}>
            <Button
              type="text"
              size="small"
              icon={<FolderInput size={14} />}
              aria-label={t("knowledgeBases.moveEntry")}
              onClick={(event) => {
                event.stopPropagation();
                openMoveEntry(document);
              }}
            />
          </Tooltip>
          <Popconfirm
            title={
              document.is_dir
                ? t("knowledgeBases.deleteFolderConfirm")
                : t("knowledgeBases.deleteDocumentConfirm")
            }
            onConfirm={() => void deleteDocument(document.id)}
          >
            <Button
              type="text"
              danger
              size="small"
              icon={<Trash2 size={14} />}
              aria-label={t("common.delete")}
            />
          </Popconfirm>
        </>
      ) : null}
    </div>
  );
}

export interface KnowledgeEntryNameProps {
  document: KnowledgeDocument;
  nameClass?: string;
  canWriteSelected: boolean;
  openRenameFile: (document: KnowledgeDocument) => void;
}

export function KnowledgeEntryName({
  document,
  nameClass,
  canWriteSelected,
  openRenameFile,
}: KnowledgeEntryNameProps) {
  const { t } = useTranslation();
  const name = knowledgeBasename(document.path || document.filename);
  const ext = !document.is_dir ? fileExtensionLabel(name) : "";
  return (
    <>
      <span className={styles.filenameHover}>
        <span
          className={cx(styles.filenameText, nameClass)}
          title={document.path || name}
        >
          {name}
        </span>
        {canWriteSelected && !document.is_dir ? (
          <Tooltip title={t("knowledgeBases.renameFile")}>
            <button
              type="button"
              className={styles.filenameRenameBtn}
              data-kb-doc-actions=""
              aria-label={t("knowledgeBases.renameFile")}
              onClick={(event) => {
                event.stopPropagation();
                openRenameFile(document);
              }}
            >
              <PencilLine size={13} strokeWidth={2} aria-hidden />
            </button>
          </Tooltip>
        ) : null}
      </span>
      {ext ? <span className={styles.docExtBadge}>{ext}</span> : null}
    </>
  );
}
