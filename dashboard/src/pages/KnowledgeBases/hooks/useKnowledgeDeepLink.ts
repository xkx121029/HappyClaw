import type { App } from "antd";
import type { TFunction } from "i18next";
import { useEffect, useRef } from "react";

import type {
  KnowledgeBase,
  KnowledgeDocument,
} from "../../../api/modules/knowledgeBases";
import { resolveKnowledgeDeepLink } from "../knowledgeDeepLink";

type AppApi = ReturnType<typeof App.useApp>;

export interface UseKnowledgeDeepLinkArgs {
  searchParams: URLSearchParams;
  setSearchParams: (
    next: URLSearchParams,
    options?: { replace?: boolean },
  ) => void;
  bases: KnowledgeBase[];
  documents: KnowledgeDocument[];
  selected: KnowledgeBase | null;
  detailLoading: boolean;
  selectBase: (base: KnowledgeBase) => void;
  openDocumentPreview: (document: KnowledgeDocument) => Promise<void>;
  setCurrentFolder: (folder: string) => void;
  message: AppApi["message"];
  t: TFunction;
}

/** Opens a `?kb=&doc=` citation link once the base list and documents have loaded. */
export function useKnowledgeDeepLink({
  searchParams,
  setSearchParams,
  bases,
  documents,
  selected,
  detailLoading,
  selectBase,
  openDocumentPreview,
  setCurrentFolder,
  message,
  t,
}: UseKnowledgeDeepLinkArgs) {
  const deepLinkConsumedRef = useRef<string | null>(null);

  useEffect(() => {
    const kb = searchParams.get("kb");
    const doc = searchParams.get("doc");
    if (!kb || !doc) return;
    const key = `${kb}:${doc}`;
    if (deepLinkConsumedRef.current === key) return;
    if (bases.length === 0) return;

    const clearDeepLinkParams = () => {
      const next = new URLSearchParams(searchParams);
      next.delete("kb");
      next.delete("doc");
      setSearchParams(next, { replace: true });
    };

    const base = bases.find((row) => row.id === kb);
    if (!base) {
      deepLinkConsumedRef.current = key;
      message.error(t("chat.citationDeepLinkFailed"));
      clearDeepLinkParams();
      return;
    }

    if (selected?.id !== kb) {
      selectBase(base);
      return;
    }

    if (detailLoading) return;

    const resolved = resolveKnowledgeDeepLink({
      kb,
      doc,
      bases,
      documents,
    });
    if (!resolved) {
      deepLinkConsumedRef.current = key;
      message.error(t("chat.citationDeepLinkFailed"));
      clearDeepLinkParams();
      return;
    }

    deepLinkConsumedRef.current = key;
    setCurrentFolder(resolved.folder);
    const full = documents.find((row) => row.id === resolved.document.id);
    if (full) {
      void openDocumentPreview(full);
    }
    clearDeepLinkParams();
    // selectBase / openDocumentPreview are stable-enough for this one-shot deep link;
    // including them would re-fire while loadDetail is in flight.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deep-link one-shot
  }, [
    bases,
    detailLoading,
    documents,
    message,
    searchParams,
    selected?.id,
    setSearchParams,
    t,
  ]);
}
