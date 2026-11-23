import type { TableColumnsType } from "antd";
import { Tag, Tooltip } from "antd";
import type { TFunction } from "i18next";
import type { ReactNode } from "react";

import type { KnowledgeDocument } from "../../../api/modules/knowledgeBases";
import { formatServerDateTime } from "../../../utils/formatMessageTime";
import { knowledgeBasename } from "../knowledgeFolder";
import { documentStatusColor } from "../knowledgeFileTypes";
import styles from "../index.module.less";
import { DocumentFormatIcon } from "./DocumentFormatIcon";

export interface DocumentTableColumnsParams {
  t: TFunction;
  timeZone: string | undefined;
  canWriteSelected: boolean;
  openDocumentPreview: (
    document: KnowledgeDocument,
    mode?: "file" | "chunks",
  ) => Promise<void>;
  renderEntryName: (document: KnowledgeDocument) => ReactNode;
  renderDocumentActions: (document: KnowledgeDocument) => ReactNode;
}

export function buildDocumentTableColumns({
  t,
  timeZone,
  canWriteSelected,
  openDocumentPreview,
  renderEntryName,
  renderDocumentActions,
}: DocumentTableColumnsParams): TableColumnsType<KnowledgeDocument> {
  return [
  {
    title: t("knowledgeBases.filename"),
    key: "filename",
    ellipsis: true,
    render: (_, document) => {
      const name = knowledgeBasename(
        document.path || document.filename,
      );
      return (
        <span className={styles.tableFilename}>
          <DocumentFormatIcon
            filename={name}
            size={13}
            className={styles.docTableIcon}
            isDir={document.is_dir}
          />
          {renderEntryName(document)}
        </span>
      );
    },
  },
  {
    title: t("knowledgeBases.entryType"),
    key: "entry_type",
    width: 88,
    render: (_, document) =>
      document.is_dir
        ? t("knowledgeBases.folder")
        : t("knowledgeBases.file"),
  },
  {
    title: t("knowledgeBases.status"),
    key: "status",
    width: 100,
    render: (_, document) =>
      document.is_dir ? (
        "—"
      ) : (
        <Tooltip
          title={document.error_message || undefined}
        >
          <Tag
            color={documentStatusColor(
              document.status,
            )}
          >
            {t(
              `knowledgeBases.statusesShort.${document.status}`,
            )}
          </Tag>
        </Tooltip>
      ),
  },
  {
    title: t("knowledgeBases.chunks"),
    dataIndex: "chunk_count",
    key: "chunk_count",
    width: 80,
    render: (chunkCount: number, document) =>
      document.is_dir ? (
        "—"
      ) : (
        <button
          type="button"
          className={styles.chunkCountButton}
          disabled={!chunkCount}
          onClick={(event) => {
            event.stopPropagation();
            void openDocumentPreview(
              document,
              "chunks",
            );
          }}
        >
          {chunkCount}
        </button>
      ),
  },
  {
    title: t("knowledgeBases.updatedAt"),
    dataIndex: "updated_at",
    key: "updated_at",
    width: 170,
    render: (updatedAt: number) =>
      formatServerDateTime(updatedAt, timeZone),
  },
  {
    title: t("common.actions"),
    key: "actions",
    width: canWriteSelected ? 120 : 48,
    render: (_, document) => (
      <div
        className={styles.tableActions}
        data-kb-doc-actions=""
        onClick={(event) => event.stopPropagation()}
      >
        {renderDocumentActions(document)}
      </div>
    ),
  },
  ];
}
