import type {
  Dispatch,
  DragEvent,
  MutableRefObject,
  PointerEventHandler,
  ReactNode,
  SetStateAction,
} from "react";
import {
  Alert,
  Button,
  Empty,
  Progress,
  Segmented,
  Spin,
  Tag,
  Tooltip,
  Tree,
  Typography,
} from "antd";
import {
  FilePlus,
  FileUp,
  FolderPlus,
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  List as ListIcon,
  Signpost,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";

import { ResizableTable } from "../../../components/ResizableTable";
import StreamSetupGuide from "../../../components/StreamSetupGuide/StreamSetupGuide";
import { OctopEmptyMascot } from "../../../components/EmptyState";
import type {
  KnowledgeCapability,
  KnowledgeDocument,
} from "../../../api/modules/knowledgeBases";
import {
  DEFAULT_KNOWLEDGE_LIMITS,
  type KnowledgeBase,
} from "../../../api/modules/knowledgeBases";
import type { CardTableViewMode } from "../../../hooks/useCardTableView";
import { formatBytes } from "../../../utils/embeddingDownload";
import { formatServerDateTime } from "../../../utils/formatMessageTime";
import skillStyles from "../../Agent/Skills/index.module.less";
import {
  KNOWLEDGE_DOC_TREE_ROOT,
  isDirectKnowledgeChild,
  knowledgeBasename,
  knowledgeBreadcrumb,
  shouldOpenKnowledgeFolder,
} from "../knowledgeFolder";
import {
  BASE_DOCUMENT_TYPES,
  OCR_DOCUMENT_TYPES,
  documentStatusColor,
} from "../knowledgeFileTypes";
import {
  isKnowledgeDocumentLimitReached,
  knowledgeDocumentCap,
} from "../knowledgeLimits";
import type { DocTreeNode } from "../knowledgeDocTree";
import styles from "../index.module.less";
import { buildDocumentTableColumns } from "./documentTableColumns";
import { DocumentFormatIcon } from "./DocumentFormatIcon";

export interface KnowledgeDetailsPaneProps {
  selected: KnowledgeBase | null;
  detailLoading: boolean;
  isMobile: boolean;
  setMobilePane: (pane: "list" | "detail") => void;
  dragActive: boolean;
  setDragActive: Dispatch<SetStateAction<boolean>>;
  uploadDocuments: (files: FileList | File[] | null) => Promise<void>;
  resetDragActive: () => void;
  setCurrentFolder: Dispatch<SetStateAction<string>>;
  viewMode: CardTableViewMode;
  onDocsViewChange: (value: string | number) => void;
  uploadRef: MutableRefObject<HTMLInputElement | null>;
  canWriteSelected: boolean;
  capability: KnowledgeCapability | null;
  openCreateTextDocument: () => void;
  docTreeCollapsed: boolean;
  docTreeWidth: number;
  docTreeData: DocTreeNode[];
  currentFolder: string;
  docTreeExpanded: string[];
  setDocTreeExpanded: Dispatch<SetStateAction<string[]>>;
  onDocTreeResizeStart: PointerEventHandler<HTMLDivElement>;
  toggleDocTree: () => void;
  dragDepthRef: MutableRefObject<number>;
  setFolderName: (name: string) => void;
  setFolderModalOpen: (open: boolean) => void;
  openDocumentPreview: (
    document: KnowledgeDocument,
    mode?: "file" | "chunks",
  ) => Promise<void>;
  uploadState: {
    baseId: string;
    filename: string;
    index: number;
    total: number;
    percent: number;
  } | null;
  documents: KnowledgeDocument[];
  showCardView: boolean;
  renderEntryName: (document: KnowledgeDocument, nameClass?: string) => ReactNode;
  renderDocumentActions: (document: KnowledgeDocument) => ReactNode;
  timeZone: string;
}

/** The selected base: path breadcrumb, view switcher, folder tree and document list. */
export function KnowledgeDetailsPane({
  selected,
  detailLoading,
  isMobile,
  setMobilePane,
  dragActive,
  setDragActive,
  uploadDocuments,
  resetDragActive,
  setCurrentFolder,
  viewMode,
  onDocsViewChange,
  uploadRef,
  canWriteSelected,
  capability,
  openCreateTextDocument,
  docTreeCollapsed,
  docTreeWidth,
  docTreeData,
  currentFolder,
  docTreeExpanded,
  setDocTreeExpanded,
  onDocTreeResizeStart,
  toggleDocTree,
  dragDepthRef,
  setFolderName,
  setFolderModalOpen,
  openDocumentPreview,
  uploadState,
  documents,
  showCardView,
  renderEntryName,
  renderDocumentActions,
  timeZone,
}: KnowledgeDetailsPaneProps) {
  const { t } = useTranslation();
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
  const folderEntries = documents
    .filter((document) =>
      isDirectKnowledgeChild(document.path || document.filename, currentFolder),
    )
    .sort((a, b) => {
      const dirDelta = Number(Boolean(b.is_dir)) - Number(Boolean(a.is_dir));
      if (dirDelta !== 0) return dirDelta;
      return knowledgeBasename(a.path || a.filename).localeCompare(
        knowledgeBasename(b.path || b.filename),
      );
    });
  const folderCrumbs = knowledgeBreadcrumb(
    currentFolder,
    selected?.name || t("knowledgeBases.documents"),
  );
  const uploadingThisBase = uploadState?.baseId === selected?.id;
  const uploadBusy = uploadState !== null;
  const canDropUpload =
    canWriteSelected && usable && !isAtDocumentLimit && !uploadBusy;

  const handleDocsDragEnter = (event: DragEvent<HTMLDivElement>) => {
    if (!canDropUpload) return;
    if (![...event.dataTransfer.types].includes("Files")) return;
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current += 1;
    setDragActive(true);
  };

  const handleDocsDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (!canDropUpload && !dragActive) return;
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragActive(false);
  };

  const handleDocsDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!canDropUpload) return;
    if (![...event.dataTransfer.types].includes("Files")) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
  };

  const handleDocsDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    resetDragActive();
    if (!canDropUpload) return;
    void uploadDocuments(event.dataTransfer.files);
  };
  return (
    <section className={styles.detail}>
      {detailLoading ? (
        <div className={styles.detailLoading}>
          <Spin />
        </div>
      ) : null}
      {!selected && !detailLoading ? (
        <div className={styles.emptyDetail}>
          <StreamSetupGuide
            className={styles.emptyGuide}
            wide
            plain
            icon={<OctopEmptyMascot />}
            title={t("knowledgeBases.selectBaseTitle")}
            description={t("knowledgeBases.selectBaseDesc")}
            steps={[
              {
                label: t("knowledgeBases.selectBaseStepPick"),
                detail: t("knowledgeBases.selectBaseStepPickDetail"),
              },
              {
                label: t("knowledgeBases.selectBaseStepUpload"),
                detail: t("knowledgeBases.selectBaseStepUploadDetail"),
              },
              {
                label: t("knowledgeBases.selectBaseStepUse"),
                detail: t("knowledgeBases.selectBaseStepUseDetail"),
              },
            ]}
          />
        </div>
      ) : !selected ? null : (
        <div
          className={cx(
            styles.detailBody,
            dragActive && styles.detailBodyDropActive,
          )}
          onDragEnter={handleDocsDragEnter}
          onDragLeave={handleDocsDragLeave}
          onDragOver={handleDocsDragOver}
          onDrop={handleDocsDrop}
        >
          {dragActive && canDropUpload ? (
            <div className={styles.dropOverlay} aria-hidden>
              <FileUp size={36} strokeWidth={1.75} />
              <span>{t("knowledgeBases.dropToUpload")}</span>
            </div>
          ) : null}
          <div
            className={cx(skillStyles.gridToolbar, styles.docsToolbar)}
          >
            <div className={styles.toolbarStart}>
              {isMobile ? (
                <button
                  type="button"
                  className={styles.mobileBack}
                  onClick={() => setMobilePane("list")}
                  aria-label={t("knowledgeBases.backToList")}
                >
                  <ChevronLeft size={18} />
                </button>
              ) : null}
              <nav
                className={styles.pathBreadcrumb}
                aria-label={t("knowledgeBases.pathBreadcrumb")}
              >
                <Signpost
                  size={14}
                  className={styles.pathBreadcrumbIcon}
                  aria-hidden
                />
                {folderCrumbs.map((seg, index) => {
                  const isLast = index === folderCrumbs.length - 1;
                  return (
                    <span
                      key={`${seg.path}:${index}`}
                      className={styles.pathBreadcrumbSegment}
                    >
                      {index > 0 ? (
                        <span
                          className={styles.pathBreadcrumbSep}
                          aria-hidden
                        >
                          /
                        </span>
                      ) : null}
                      {isLast ? (
                        <span
                          className={styles.pathBreadcrumbCurrent}
                          title={seg.label}
                        >
                          <span className={styles.pathBreadcrumbLabel}>
                            {seg.label}
                          </span>
                        </span>
                      ) : (
                        <button
                          type="button"
                          className={styles.pathBreadcrumbLink}
                          onClick={() => setCurrentFolder(seg.path)}
                          title={seg.label}
                        >
                          <span className={styles.pathBreadcrumbLabel}>
                            {seg.label}
                          </span>
                        </button>
                      )}
                    </span>
                  );
                })}
              </nav>
            </div>
            <div className={skillStyles.gridToolbarRight}>
              <Segmented
                size="small"
                value={viewMode}
                onChange={onDocsViewChange}
                options={[
                  {
                    value: "card",
                    label: (
                      <span className={skillStyles.viewModeLabel}>
                        <LayoutGrid size={14} />
                        {t("knowledgeBases.viewCard")}
                      </span>
                    ),
                  },
                  {
                    value: "table",
                    label: (
                      <span className={skillStyles.viewModeLabel}>
                        <ListIcon size={14} />
                        {t("knowledgeBases.viewTable")}
                      </span>
                    ),
                  },
                ]}
              />
              <input
                ref={uploadRef}
                className={styles.fileInput}
                type="file"
                multiple
                accept={supportedDocumentTypes}
                onChange={(event) =>
                  void uploadDocuments(event.target.files)
                }
              />
              {canWriteSelected ? (
                <Button
                  icon={<FolderPlus size={14} />}
                  onClick={() => {
                    setFolderName("");
                    setFolderModalOpen(true);
                  }}
                >
                  {t("knowledgeBases.createFolder")}
                </Button>
              ) : null}
              {canWriteSelected ? (
                <Button
                  icon={<FilePlus size={14} />}
                  disabled={isAtDocumentLimit}
                  onClick={openCreateTextDocument}
                >
                  {t("knowledgeBases.createFile")}
                </Button>
              ) : null}
              {canWriteSelected ? (
                <Button
                  type="primary"
                  icon={<FileUp size={14} />}
                  loading={uploadingThisBase}
                  disabled={isAtDocumentLimit || uploadBusy}
                  onClick={() => uploadRef.current?.click()}
                >
                  {t("knowledgeBases.upload")}
                </Button>
              ) : null}
            </div>
          </div>
          <div className={styles.docsPathRow}>
            <span className={skillStyles.gridCount}>
              {documentCap === null
                ? t("knowledgeBases.documentCount", {
                    count: fileCount,
                  })
                : t("knowledgeBases.documentLimit", {
                    count: fileCount,
                    max: documentCap,
                  })}
            </span>
            {canWriteSelected ? (
              <Typography.Text
                type="secondary"
                className={styles.uploadHint}
                ellipsis={{ tooltip: true }}
              >
                {t(
                  capability?.ocr?.usable
                    ? "knowledgeBases.uploadHintOcr"
                    : "knowledgeBases.uploadHint",
                  {
                    sizeMb: Math.round(
                      limits.max_document_bytes / (1024 * 1024),
                    ),
                  },
                )}
              </Typography.Text>
            ) : null}
          </div>
          <div
            className={cx(
              styles.docsSplit,
              !isMobile && styles.docsSplitFramed,
            )}
          >
            {!isMobile && !docTreeCollapsed ? (
              <aside
                className={styles.docTreePane}
                style={{ width: docTreeWidth }}
                aria-label={t("knowledgeBases.docTree")}
              >
                <div className={styles.docTreeHeader}>
                  {t("knowledgeBases.folderTreeTitle")}
                </div>
                <div className={styles.docTreeScroll}>
                  <Tree
                    blockNode
                    treeData={docTreeData}
                    selectedKeys={[
                      currentFolder || KNOWLEDGE_DOC_TREE_ROOT,
                    ]}
                    expandedKeys={docTreeExpanded}
                    onExpand={(keys) =>
                      setDocTreeExpanded(keys.map(String))
                    }
                    onSelect={(_keys, info) => {
                      if (!info.selected) return;
                      const node = info.node as DocTreeNode;
                      setCurrentFolder(node.path);
                    }}
                  />
                </div>
              </aside>
            ) : null}
            {!isMobile ? (
              <div
                data-split-divider=""
                className={cx(
                  styles.docTreeDivider,
                  docTreeCollapsed && styles.docTreeDividerCollapsed,
                )}
              >
                {!docTreeCollapsed ? (
                  <div
                    className={styles.docTreeResize}
                    role="separator"
                    aria-orientation="vertical"
                    aria-label={t("knowledgeBases.resizeDocTree")}
                    onPointerDown={onDocTreeResizeStart}
                  />
                ) : null}
                <Tooltip
                  title={
                    docTreeCollapsed
                      ? t("knowledgeBases.showDocTree")
                      : t("knowledgeBases.hideDocTree")
                  }
                >
                  <button
                    type="button"
                    className={styles.docTreeToggle}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleDocTree();
                    }}
                    onMouseDown={(event) => event.stopPropagation()}
                    aria-label={
                      docTreeCollapsed
                        ? t("knowledgeBases.showDocTree")
                        : t("knowledgeBases.hideDocTree")
                    }
                  >
                    {docTreeCollapsed ? (
                      <ChevronRight size={14} strokeWidth={2} />
                    ) : (
                      <ChevronLeft size={14} strokeWidth={2} />
                    )}
                  </button>
                </Tooltip>
              </div>
            ) : null}
            <div className={styles.docsMain}>
              {uploadingThisBase && uploadState ? (
                <div
                  className={styles.uploadProgress}
                  aria-live="polite"
                >
                  <Typography.Text
                    className={styles.uploadProgressLabel}
                    ellipsis={{ tooltip: uploadState.filename }}
                  >
                    {uploadState.total > 1
                      ? t("knowledgeBases.uploadingMany", {
                          name: uploadState.filename,
                          index: uploadState.index,
                          total: uploadState.total,
                        })
                      : t("knowledgeBases.uploading", {
                          name: uploadState.filename,
                        })}
                  </Typography.Text>
                  <Progress
                    percent={uploadState.percent}
                    size="small"
                    status="active"
                  />
                </div>
              ) : null}
              {isAtDocumentLimit ? (
                <Alert
                  className={styles.limitAlert}
                  type="info"
                  showIcon
                  message={t("knowledgeBases.documentLimitReached", {
                    count: documentCap ?? limits.max_docs_per_kb,
                  })}
                />
              ) : null}
              {folderEntries.length === 0 ? (
                !currentFolder && documents.length === 0 ? (
                  <StreamSetupGuide
                    className={styles.emptyGuide}
                    wide
                    plain
                    icon={<OctopEmptyMascot />}
                    title={t("knowledgeBases.emptyDocumentsTitle")}
                    description={
                      canWriteSelected
                        ? t("knowledgeBases.emptyDocumentsDesc")
                        : t("knowledgeBases.emptyDocumentsReadonlyDesc")
                    }
                    steps={[
                      {
                        label: t(
                          "knowledgeBases.emptyDocumentsStepUpload",
                        ),
                        detail: t(
                          "knowledgeBases.emptyDocumentsStepUploadDetail",
                        ),
                      },
                      {
                        label: t(
                          "knowledgeBases.emptyDocumentsStepWrite",
                        ),
                        detail: t(
                          "knowledgeBases.emptyDocumentsStepWriteDetail",
                        ),
                      },
                      {
                        label: t(
                          "knowledgeBases.emptyDocumentsStepUse",
                        ),
                        detail: t(
                          "knowledgeBases.emptyDocumentsStepUseDetail",
                        ),
                      },
                    ]}
                    primaryAction={
                      canWriteSelected
                        ? {
                            label: t("knowledgeBases.upload"),
                            onClick: () => uploadRef.current?.click(),
                            icon: <FileUp size={14} />,
                            loading: uploadingThisBase,
                            disabled: isAtDocumentLimit || uploadBusy,
                          }
                        : undefined
                    }
                    secondaryAction={
                      canWriteSelected
                        ? {
                            label: t("knowledgeBases.createFile"),
                            onClick: openCreateTextDocument,
                            icon: <FilePlus size={14} />,
                            type: "default",
                            disabled: isAtDocumentLimit,
                          }
                        : undefined
                    }
                  />
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t("knowledgeBases.emptyDocuments")}
                  />
                )
              ) : showCardView ? (
                <div className={styles.docCardGrid}>
                  {folderEntries.map((document) => {
                    const name = knowledgeBasename(
                      document.path || document.filename,
                    );
                    return (
                      <div
                        key={document.id}
                        className={styles.docCard}
                        role={document.is_dir ? "button" : undefined}
                        onClick={(event) => {
                          if (
                            !shouldOpenKnowledgeFolder(
                              Boolean(document.is_dir),
                              event,
                            )
                          ) {
                            return;
                          }
                          setCurrentFolder(
                            document.path || document.filename,
                          );
                        }}
                      >
                        <div className={styles.docCardHeader}>
                          <DocumentFormatIcon
                            filename={name}
                            size={14}
                            isDir={document.is_dir}
                          />
                          <div className={styles.docCardTitleBlock}>
                            <div className={styles.docCardTitleRow}>
                              {renderEntryName(
                                document,
                                styles.docCardName,
                              )}
                            </div>
                            <div className={styles.docCardMeta}>
                              {document.is_dir
                                ? t("knowledgeBases.folder")
                                : `${formatBytes(
                                    document.byte_size,
                                  )} · ${t(
                                    "knowledgeBases.chunkCount",
                                    {
                                      count: document.chunk_count,
                                    },
                                  )}`}
                            </div>
                          </div>
                          <span
                            data-kb-doc-actions=""
                            onClick={(event) => event.stopPropagation()}
                          >
                            {renderDocumentActions(document)}
                          </span>
                        </div>
                        {document.is_dir ? null : (
                          <div className={styles.docCardFooter}>
                            <Tooltip
                              title={
                                document.error_message ||
                                t(
                                  `knowledgeBases.statuses.${document.status}`,
                                )
                              }
                            >
                              <Tag
                                className={styles.docStatusTag}
                                color={documentStatusColor(
                                  document.status,
                                )}
                              >
                                {t(
                                  `knowledgeBases.statusesShort.${document.status}`,
                                )}
                              </Tag>
                            </Tooltip>
                            <span
                              className={styles.docUpdatedAt}
                              title={formatServerDateTime(
                                document.updated_at,
                                timeZone,
                              )}
                            >
                              {formatServerDateTime(
                                document.updated_at,
                                timeZone,
                              )}
                            </span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <ResizableTable
                  storageKey="kb-documents"
                  size="small"
                  rowKey="id"
                  pagination={false}
                  scroll={{ x: 720 }}
                  dataSource={folderEntries}
                  onRow={(document) => ({
                    onClick: document.is_dir
                      ? (event) => {
                          if (!shouldOpenKnowledgeFolder(true, event)) {
                            return;
                          }
                          setCurrentFolder(
                            document.path || document.filename,
                          );
                        }
                      : undefined,
                  })}
                  locale={{
                    emptyText: t("knowledgeBases.emptyDocuments"),
                  }}
                  columns={buildDocumentTableColumns({
                    t,
                    timeZone,
                    canWriteSelected,
                    openDocumentPreview,
                    renderEntryName,
                    renderDocumentActions,
                  })}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
