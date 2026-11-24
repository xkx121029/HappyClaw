import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Input,
  Modal,
  Segmented,
  Spin,
  Tooltip,
} from "antd";
import type { InputRef } from "antd/es/input";
import cx from "classnames";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  ListTree,
  Maximize2,
  Minimize2,
  Search,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type { KnowledgeDocument } from "../../../api/modules/knowledgeBases";
import type { DocumentPreviewCoreProps } from "../../../components/DocumentPreviewCore";
import DocumentPreviewCore from "../../../components/DocumentPreviewCore";
import DocumentPreviewLoading from "../../../components/DocumentPreviewLoading";
import Markdown from "../../../components/Markdown";
import type { DocKind } from "../../../utils/docKind";
import { isImeComposing } from "../../../utils/ime";
import { stripFrontmatter } from "../../../utils/markdown";
import styles from "../index.module.less";
import type { MdOutlineItem } from "../mdOutline";

export interface DocumentPreviewModalProps {
  previewOpen: boolean;
  requestClosePreview: () => void;
  previewFilename: string;
  previewMode: "file" | "chunks";
  setPreviewMode: Dispatch<SetStateAction<"file" | "chunks">>;
  selectedId: string | null;
  previewDocId: string | null;
  chunkItems: { ordinal: number; text: string }[];
  chunkLoading: boolean;
  chunkError: string | null;
  loadDocumentChunks: (kbId: string, documentId: string) => Promise<void>;
  previewFileAvailable: boolean;
  previewNavIndex: number;
  previewableDocs: KnowledgeDocument[];
  openDocumentPreview: (
    document: KnowledgeDocument,
    mode?: "file" | "chunks",
  ) => Promise<void>;
  previewMaximized: boolean;
  togglePreviewFullscreen: () => void;
  previewHasOriginal: boolean;
  downloadDocumentOriginal: (
    documentId: string,
    filename: string,
  ) => Promise<void>;
  isRichPreview: boolean;
  isMobile: boolean;
  previewKind: DocKind | null;
  fetchPreviewBlob: DocumentPreviewCoreProps["fetchBlob"];
  previewAsMarkdown: boolean;
  mdOutlineItems: MdOutlineItem[];
  mdOutlineOpen: boolean;
  setMdOutlineOpen: Dispatch<SetStateAction<boolean>>;
  mdActiveOutlineIndex: number;
  scrollToMdHeading: (item: MdOutlineItem) => void;
  mdFindOpen: boolean;
  setMdFindOpen: Dispatch<SetStateAction<boolean>>;
  mdFindQuery: string;
  setMdFindQuery: Dispatch<SetStateAction<string>>;
  mdFindIndex: number;
  setMdFindIndex: Dispatch<SetStateAction<number>>;
  mdFindHitCount: number;
  mdFindInputRef: MutableRefObject<InputRef | null>;
  mdBodyRef: MutableRefObject<HTMLDivElement | null>;
  jumpMdFind: (direction: 1 | -1) => void;
  previewLoading: boolean;
  previewText: string;
}

export function DocumentPreviewModal({
  previewOpen,
  requestClosePreview,
  previewFilename,
  previewMode,
  setPreviewMode,
  selectedId,
  previewDocId,
  chunkItems,
  chunkLoading,
  chunkError,
  loadDocumentChunks,
  previewFileAvailable,
  previewNavIndex,
  previewableDocs,
  openDocumentPreview,
  previewMaximized,
  togglePreviewFullscreen,
  previewHasOriginal,
  downloadDocumentOriginal,
  isRichPreview,
  isMobile,
  previewKind,
  fetchPreviewBlob,
  previewAsMarkdown,
  mdOutlineItems,
  mdOutlineOpen,
  setMdOutlineOpen,
  mdActiveOutlineIndex,
  scrollToMdHeading,
  mdFindOpen,
  setMdFindOpen,
  mdFindQuery,
  setMdFindQuery,
  mdFindIndex,
  setMdFindIndex,
  mdFindHitCount,
  mdFindInputRef,
  mdBodyRef,
  jumpMdFind,
  previewLoading,
  previewText,
}: DocumentPreviewModalProps) {
  const { t } = useTranslation();
  return (
    <Modal
      title={
        <div className={styles.previewModalTitleRow}>
          <span
            className={styles.previewModalTitleText}
            title={previewFilename || undefined}
          >
            {previewFilename || t("knowledgeBases.previewDocument")}
          </span>
          <Segmented
            size="small"
            value={previewMode}
            onChange={(value) => {
              const next = value === "chunks" ? "chunks" : "file";
              setPreviewMode(next);
              if (
                next === "chunks" &&
                selectedId &&
                previewDocId &&
                chunkItems.length === 0
              ) {
                void loadDocumentChunks(selectedId, previewDocId);
              }
            }}
            options={[
              {
                label: t("knowledgeBases.previewFile"),
                value: "file",
                disabled: !previewFileAvailable,
              },
              { label: t("knowledgeBases.previewChunks"), value: "chunks" },
            ]}
          />
          {previewNavIndex >= 0 ? (
            <span className={styles.previewModalNav}>
              <Tooltip title={t("knowledgeBases.previewPrev")}>
                <button
                  type="button"
                  className={styles.previewModalExpandBtn}
                  aria-label={t("knowledgeBases.previewPrev")}
                  disabled={previewNavIndex <= 0}
                  onClick={() => {
                    const prev = previewableDocs[previewNavIndex - 1];
                    if (prev) void openDocumentPreview(prev);
                  }}
                >
                  <ChevronLeft size={14} strokeWidth={2} aria-hidden />
                </button>
              </Tooltip>
              <span className={styles.previewModalNavMeta}>
                {previewNavIndex + 1} / {previewableDocs.length}
              </span>
              <Tooltip title={t("knowledgeBases.previewNext")}>
                <button
                  type="button"
                  className={styles.previewModalExpandBtn}
                  aria-label={t("knowledgeBases.previewNext")}
                  disabled={previewNavIndex >= previewableDocs.length - 1}
                  onClick={() => {
                    const next = previewableDocs[previewNavIndex + 1];
                    if (next) void openDocumentPreview(next);
                  }}
                >
                  <ChevronRight size={14} strokeWidth={2} aria-hidden />
                </button>
              </Tooltip>
            </span>
          ) : null}
          <Tooltip
            title={
              previewMaximized
                ? t("knowledgeBases.exitFullscreen")
                : t("knowledgeBases.enterFullscreen")
            }
          >
            <button
              type="button"
              className={styles.previewModalExpandBtn}
              aria-label={
                previewMaximized
                  ? t("knowledgeBases.exitFullscreen")
                  : t("knowledgeBases.enterFullscreen")
              }
              onClick={togglePreviewFullscreen}
            >
              {previewMaximized ? (
                <Minimize2 size={14} strokeWidth={2} aria-hidden />
              ) : (
                <Maximize2 size={14} strokeWidth={2} aria-hidden />
              )}
            </button>
          </Tooltip>
          <Tooltip title={t("common.close", "关闭")}>
            <button
              type="button"
              className={styles.previewModalExpandBtn}
              aria-label={t("common.close", "关闭")}
              onClick={requestClosePreview}
            >
              <X size={14} strokeWidth={2} aria-hidden />
            </button>
          </Tooltip>
        </div>
      }
      open={previewOpen}
      onCancel={requestClosePreview}
      closable={false}
      footer={
        previewDocId && previewHasOriginal ? (
          <Button
            icon={<Download size={14} />}
            onClick={() =>
              void downloadDocumentOriginal(previewDocId, previewFilename)
            }
          >
            {t("knowledgeBases.downloadOriginal")}
          </Button>
        ) : null
      }
      width={
        previewMaximized ? "100vw" : isRichPreview ? "min(1200px, 92vw)" : 720
      }
      centered={!previewMaximized}
      destroyOnHidden
      className={previewMaximized ? styles.previewModalMaximized : undefined}
      wrapClassName={styles.previewModalWrap}
      style={
        previewMaximized
          ? { top: 0, maxWidth: "100vw" }
          : // Cap the dialog itself (antd paddings + responsive margins from
            // styles/layout.css stack on top of the content max-height).
            { maxHeight: "calc(100vh - 48px)" }
      }
      classNames={{
        content: previewMaximized
          ? styles.previewModalContentMaximized
          : styles.previewModalContent,
      }}
      styles={{
        body: {
          // Desired height only — the content flex column + max-height
          // (see .previewModalContent) shrinks this when the viewport
          // cannot fit it, so the wrap never grows a scrollbar.
          height: previewMaximized ? undefined : "78vh",
          flex: previewMaximized ? "1 1 auto" : "0 1 auto",
          minHeight: 0,
          padding: 12,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        },
      }}
    >
      {previewMode === "chunks" ? (
        <div className={styles.chunkList}>
          {chunkLoading ? (
            <Spin />
          ) : chunkError ? (
            <Alert type="error" showIcon message={chunkError} />
          ) : chunkItems.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("knowledgeBases.chunksEmpty")}
            />
          ) : (
            chunkItems.map((chunk) => (
              <article key={chunk.ordinal} className={styles.chunkCard}>
                <div className={styles.chunkCardLabel}>
                  {t("knowledgeBases.chunkLabel", { n: chunk.ordinal + 1 })}
                </div>
                <pre className={styles.chunkCardText}>{chunk.text}</pre>
              </article>
            ))
          )}
        </div>
      ) : previewKind && previewDocId ? (
        <div
          className={styles.richPreviewBody}
          data-preview-fullscreen-root=""
        >
          <DocumentPreviewCore
            key={previewDocId}
            kind={previewKind}
            filename={previewFilename}
            fetchBlob={fetchPreviewBlob}
            onDownload={
              previewHasOriginal
                ? () =>
                    void downloadDocumentOriginal(
                      previewDocId,
                      previewFilename,
                    )
                : undefined
            }
          />
        </div>
      ) : previewAsMarkdown ? (
        <div className={styles.mdPreviewWrap} data-preview-fullscreen-root="">
          <div className={styles.mdPreviewToolbar}>
            <Tooltip
              title={
                mdOutlineItems.length === 0
                  ? t("knowledgeBases.mdOutlineEmpty")
                  : t("knowledgeBases.mdOutline")
              }
            >
              <span className={styles.mdOutlineToggleHost}>
                <button
                  type="button"
                  className={styles.previewModalExpandBtn}
                  aria-label={t("knowledgeBases.mdOutline")}
                  disabled={mdOutlineItems.length === 0}
                  onClick={() => setMdOutlineOpen((v) => !v)}
                >
                  <ListTree size={14} strokeWidth={2} aria-hidden />
                </button>
              </span>
            </Tooltip>
            {mdOutlineItems.length > 0 ? (
              <span className={styles.mdPreviewMeta}>
                {t("knowledgeBases.mdOutlineCount", {
                  count: mdOutlineItems.length,
                })}
              </span>
            ) : null}
            <span className={styles.mdPreviewToolbarSpacer} />
            {mdFindOpen ? (
              <span className={styles.mdFindBar}>
                <Input
                  ref={mdFindInputRef}
                  size="small"
                  allowClear
                  value={mdFindQuery}
                  placeholder={t("knowledgeBases.mdFindPlaceholder")}
                  onChange={(event) => {
                    setMdFindQuery(event.target.value);
                    setMdFindIndex(0);
                  }}
                  onPressEnter={(event) => {
                    if (!isImeComposing(event)) jumpMdFind(1);
                  }}
                  onKeyDown={(event) => {
                    if (isImeComposing(event)) return;
                    if (event.key === "Escape") {
                      event.stopPropagation();
                      setMdFindOpen(false);
                      setMdFindQuery("");
                    }
                  }}
                  className={styles.mdFindInput}
                />
                <span className={styles.mdPreviewMeta}>
                  {mdFindHitCount === 0
                    ? "0"
                    : `${Math.min(
                        mdFindIndex + 1,
                        mdFindHitCount,
                      )} / ${mdFindHitCount}`}
                </span>
                <button
                  type="button"
                  className={styles.previewModalExpandBtn}
                  aria-label={t("knowledgeBases.mdFindPrev")}
                  disabled={mdFindHitCount === 0}
                  onClick={() => jumpMdFind(-1)}
                >
                  <ChevronLeft size={14} strokeWidth={2} aria-hidden />
                </button>
                <button
                  type="button"
                  className={styles.previewModalExpandBtn}
                  aria-label={t("knowledgeBases.mdFindNext")}
                  disabled={mdFindHitCount === 0}
                  onClick={() => jumpMdFind(1)}
                >
                  <ChevronRight size={14} strokeWidth={2} aria-hidden />
                </button>
              </span>
            ) : (
              <Tooltip title={t("knowledgeBases.mdFind")}>
                <button
                  type="button"
                  className={styles.previewModalExpandBtn}
                  aria-label={t("knowledgeBases.mdFind")}
                  onClick={() => {
                    setMdFindOpen(true);
                    window.setTimeout(
                      () => mdFindInputRef.current?.focus(),
                      0,
                    );
                  }}
                >
                  <Search size={14} strokeWidth={2} aria-hidden />
                </button>
              </Tooltip>
            )}
          </div>
          <div className={styles.mdPreviewRow}>
            {mdOutlineOpen && mdOutlineItems.length > 0 && !isMobile ? (
              <nav
                className={styles.mdOutlinePanel}
                aria-label={t("knowledgeBases.mdOutline")}
              >
                {mdOutlineItems.map((item, index) => (
                  <button
                    key={index}
                    type="button"
                    className={cx(
                      styles.mdOutlineItem,
                      index === mdActiveOutlineIndex &&
                        styles.mdOutlineItemActive,
                    )}
                    style={{ paddingLeft: 10 + (item.level - 1) * 14 }}
                    title={item.title}
                    onClick={() => scrollToMdHeading(item)}
                  >
                    {item.title}
                  </button>
                ))}
              </nav>
            ) : null}
            {isMobile ? (
              <Drawer
                title={t("knowledgeBases.mdOutline")}
                placement="left"
                open={mdOutlineOpen && mdOutlineItems.length > 0}
                onClose={() => setMdOutlineOpen(false)}
                width={280}
                destroyOnHidden
              >
                {mdOutlineItems.map((item, index) => (
                  <button
                    key={index}
                    type="button"
                    className={cx(
                      styles.mdOutlineItem,
                      index === mdActiveOutlineIndex &&
                        styles.mdOutlineItemActive,
                    )}
                    style={{ paddingLeft: 10 + (item.level - 1) * 14 }}
                    title={item.title}
                    onClick={() => {
                      scrollToMdHeading(item);
                      setMdOutlineOpen(false);
                    }}
                  >
                    {item.title}
                  </button>
                ))}
              </Drawer>
            ) : null}
            <div className={styles.mdPreviewBody} ref={mdBodyRef}>
              {previewLoading ? (
                <DocumentPreviewLoading phase="file" />
              ) : previewText.trim() &&
                previewText !== t("knowledgeBases.previewEmpty") ? (
                <Markdown content={stripFrontmatter(previewText)} />
              ) : (
                <span className={styles.mdPreviewEmpty}>
                  {t("knowledgeBases.previewEmpty")}
                </span>
              )}
            </div>
          </div>
        </div>
      ) : previewLoading ? (
        <DocumentPreviewLoading phase="file" />
      ) : (
        <pre className={styles.previewBody}>{previewText}</pre>
      )}
    </Modal>
  );
}
