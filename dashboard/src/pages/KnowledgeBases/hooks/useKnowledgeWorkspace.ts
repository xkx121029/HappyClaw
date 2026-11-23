import type { App } from "antd";
import type { TFunction } from "i18next";
import { useCallback, useEffect, useRef, useState } from "react";
import type { NavigateFunction } from "react-router-dom";

import type {
  KnowledgeBase,
  KnowledgeDocument,
} from "../../../api/modules/knowledgeBases";
import { knowledgeBasesApi } from "../../../api/modules/knowledgeBases";
import { apiErrorMessage, isNotFoundApiError } from "../../../utils/apiError";
import { createDetailRequestGate } from "../../../utils/detailRequestGate";
import { setPendingAttachKnowledgeBaseId } from "../../Chat/utils/pendingAttachKnowledgeBase";

type AppApi = ReturnType<typeof App.useApp>;

export interface UseKnowledgeWorkspaceArgs {
  t: TFunction;
  message: AppApi["message"];
  modal: AppApi["modal"];
  navigate: NavigateFunction;
  isMobile: boolean;
  loadCapability: () => Promise<void>;
}

/** Base list, selection and document collection for the knowledge-bases page. */
export function useKnowledgeWorkspace({
  t,
  message,
  modal,
  navigate,
  isMobile,
  loadCapability,
}: UseKnowledgeWorkspaceArgs) {

  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selected, setSelected] = useState<KnowledgeBase | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  selectedIdRef.current = selected?.id ?? null;
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [mobilePane, setMobilePane] = useState<"list" | "detail">("list");

  const detailRequestGate = useRef(createDetailRequestGate());

  const loadBases = useCallback(async () => {
    try {
      const rows = await knowledgeBasesApi.list();
      setBases(rows);
      setSelected((current) =>
        current && !rows.some((row) => row.id === current.id) ? null : current,
      );
    } catch (error) {
      message.error(apiErrorMessage(error, t("knowledgeBases.loadFailed"), t));
    }
  }, [t]);

  const loadDetail = useCallback(
    async (id: string, options?: { silent?: boolean }) => {
      const requestId = detailRequestGate.current.begin();
      if (!options?.silent) setDetailLoading(true);
      try {
        const [base, nextDocuments] = await Promise.all([
          knowledgeBasesApi.get(id),
          knowledgeBasesApi.listDocuments(id),
        ]);
        if (!detailRequestGate.current.isCurrent(requestId)) return;
        setSelected(base);
        setDocuments(nextDocuments);
      } catch (error) {
        if (!detailRequestGate.current.isCurrent(requestId)) return;
        if (isNotFoundApiError(error)) {
          setSelected(null);
          setDocuments([]);
          return;
        }
        if (!options?.silent) {
          message.error(
            apiErrorMessage(error, t("knowledgeBases.loadFailed"), t),
          );
        }
      } finally {
        if (
          !options?.silent &&
          detailRequestGate.current.isCurrent(requestId)
        ) {
          setDetailLoading(false);
        }
      }
    },
    [t],
  );

  const selectBase = (base: KnowledgeBase) => {
    if (base.id !== selected?.id) void loadDetail(base.id);
    if (isMobile) setMobilePane("detail");
  };

  const deleteBase = async (base: KnowledgeBase) => {
    const deletedId = base.id;
    const deletingSelected = deletedId === selected?.id;
    if (deletingSelected) {
      detailRequestGate.current.begin();
      setSelected(null);
      setDocuments([]);
      setDetailLoading(false);
    }
    try {
      await knowledgeBasesApi.delete(deletedId);
      const rows = await knowledgeBasesApi.list();
      setBases(rows);
      if (deletingSelected) {
        if (isMobile) {
          setMobilePane("list");
        } else if (rows.length > 0) {
          await loadDetail(rows[0].id);
        }
      }
      message.success(t("knowledgeBases.deleted"));
    } catch (error) {
      message.error(
        apiErrorMessage(error, t("knowledgeBases.deleteFailed"), t),
      );
    }
  };

  const confirmDeleteBase = (base: KnowledgeBase) => {
    modal.confirm({
      title: t("knowledgeBases.deleteConfirm"),
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: () => deleteBase(base),
    });
  };

  const addBaseToChat = (base: KnowledgeBase) => {
    setPendingAttachKnowledgeBaseId(base.id);
    navigate("/chat", { state: { attachKnowledgeBaseId: base.id } });
  };
  useEffect(() => {
    void Promise.all([loadBases(), loadCapability()]).finally(() =>
      setLoading(false),
    );
  }, [loadBases, loadCapability]);

  useEffect(() => {
    const indexing = documents.some(
      (document) =>
        !document.is_dir &&
        (document.status === "pending" || document.status === "processing"),
    );
    if (!selected || !indexing) return;
    const timer = window.setInterval(() => {
      void loadDetail(selected.id, { silent: true });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [documents, loadDetail, selected]);
  useEffect(() => {
    if (!isMobile && !selected && bases.length > 0 && !detailLoading) {
      void loadDetail(bases[0].id);
    }
  }, [bases, detailLoading, isMobile, loadDetail, selected]);

  useEffect(() => {
    if (!isMobile) setMobilePane("list");
  }, [isMobile]);

  return {
    bases,
    selected,
    documents,
    selectedIdRef,
    loading,
    setLoading,
    detailLoading,
    refreshing,
    setRefreshing,
    mobilePane,
    setMobilePane,
    detailRequestGate,
    loadBases,
    loadDetail,
    selectBase,
    deleteBase,
    confirmDeleteBase,
    addBaseToChat,
  };
}
