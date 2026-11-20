import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  knowledgeBasesApi,
  type KnowledgeBase,
  type KnowledgeDocument,
} from "../../api/modules/knowledgeBases";
import { useAgent } from "../../context/AgentContext";
import { MobileChip } from "../components/MobileChip";
import { MobileEmpty } from "../components/MobileEmpty";
import { MobileIcon } from "../components/MobileIcon";
import { MobilePage } from "../components/MobilePage";
import { MobileSheet } from "../components/MobileSheet";
import { MobileSkeleton } from "../components/MobileSkeleton";
import { showMobileToast } from "../components/MobileToast";

const DOC_TONE: Record<string, "ok" | "warn" | "danger" | "default"> = {
  ready: "ok",
  pending: "warn",
  processing: "warn",
  failed: "danger",
};

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function KnowledgePage() {
  const { t } = useTranslation();
  const { activeAgentId, activeAgent } = useAgent();
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [current, setCurrent] = useState<KnowledgeBase | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsFailed, setDocumentsFailed] = useState(false);

  const docLabels = useMemo<Record<string, string>>(
    () => ({
      ready: t("mobile.knowledge.docReady", "已就绪"),
      pending: t("mobile.knowledge.docPending", "排队中"),
      processing: t("mobile.knowledge.docProcessing", "处理中"),
      failed: t("mobile.knowledge.docFailed", "失败"),
    }),
    [t],
  );

  const load = useCallback(async () => {
    try {
      setBases(await knowledgeBasesApi.list(activeAgentId));
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [activeAgentId]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  const openBase = async (base: KnowledgeBase) => {
    setCurrent(base);
    setDocuments([]);
    setDocumentsFailed(false);
    setDocumentsLoading(true);
    try {
      const id = base.knowledge_base_id || base.id;
      setDocuments(await knowledgeBasesApi.listDocuments(id));
    } catch {
      setDocumentsFailed(true);
      showMobileToast(t("mobile.knowledge.docsFailed", "文档加载失败"));
    } finally {
      setDocumentsLoading(false);
    }
  };

  return (
    <MobilePage
      title={t("mobile.nav.knowledgeBases", "知识库")}
      back
      subtitle={activeAgent?.name}
    >
      {loading ? (
        <MobileSkeleton rows={3} />
      ) : failed ? (
        <MobileEmpty
          icon="alert"
          title={t("mobile.knowledge.loadFailedTitle", "知识库加载失败")}
          action={
            <button
              type="button"
              className="m-btn m-btn--primary"
              onClick={() => void load()}
            >
              {t("common.retry", "重试")}
            </button>
          }
        />
      ) : bases.length === 0 ? (
        <MobileEmpty
          icon="book"
          title={t("mobile.knowledge.emptyTitle", "还没有知识库")}
          description={t(
            "mobile.knowledge.emptyDesc",
            "知识库可在桌面端创建并上传文档，手机端可以浏览与查看状态。",
          )}
        />
      ) : (
        <div className="m-stack">
          {bases.map((base) => (
            <button
              type="button"
              key={base.id}
              className="m-card is-tap"
              style={{ textAlign: "left" }}
              onClick={() => void openBase(base)}
            >
              <div className="m-rowflex">
                <span className="m-row-icon">
                  <MobileIcon name="book" size={18} />
                </span>
                <span className="m-grow">
                  <span
                    className="m-card-title m-truncate"
                    style={{ display: "block" }}
                  >
                    {base.name}
                  </span>
                  <span className="m-card-desc m-clamp2">
                    {base.description ||
                      t("mobile.knowledge.noDescription", "暂无描述")}
                  </span>
                </span>
                <MobileIcon name="chevron" size={16} />
              </div>
              <div
                className="m-rowflex m-wrap"
                style={{ marginTop: 10, gap: 6 }}
              >
                <MobileChip tone="accent">
                  {t("mobile.knowledge.docCount", "{{used}}/{{max}} 文档", {
                    used: base.doc_count,
                    max: base.max_documents,
                  })}
                </MobileChip>
                {base.default_open ? (
                  <MobileChip>
                    {t("mobile.knowledge.defaultOn", "默认开启")}
                  </MobileChip>
                ) : null}
                {base.shared ? (
                  <MobileChip>
                    {t("mobile.knowledge.shared", "共享")}
                  </MobileChip>
                ) : null}
                <MobileChip>{base.embedding_model}</MobileChip>
              </div>
            </button>
          ))}
        </div>
      )}

      <MobileSheet
        open={Boolean(current)}
        title={current?.name}
        height="half"
        onClose={() => setCurrent(null)}
      >
        {documentsLoading ? (
          <MobileSkeleton rows={4} />
        ) : documentsFailed ? (
          <MobileEmpty
            icon="alert"
            title={t("mobile.knowledge.docsFailed", "文档加载失败")}
          />
        ) : documents.length === 0 ? (
          <MobileEmpty
            icon="book"
            title={t("mobile.knowledge.noDocsTitle", "还没有文档")}
            description={t(
              "mobile.knowledge.noDocsDesc",
              "在桌面端上传文档后，这里会显示索引状态。",
            )}
          />
        ) : (
          <div className="m-group">
            {documents.map((doc) => (
              <div className="m-row" key={doc.id}>
                <span className="m-row-main">
                  <span className="m-row-title m-truncate">{doc.filename}</span>
                  <span className="m-row-sub">
                    {formatBytes(doc.byte_size)}
                    {doc.chunk_count
                      ? t("mobile.knowledge.chunkCount", " · {{n}} 段", {
                          n: doc.chunk_count,
                        })
                      : ""}
                  </span>
                </span>
                <MobileChip tone={DOC_TONE[doc.status] ?? "default"}>
                  {docLabels[doc.status] ?? doc.status}
                </MobileChip>
              </div>
            ))}
          </div>
        )}
      </MobileSheet>
    </MobilePage>
  );
}
