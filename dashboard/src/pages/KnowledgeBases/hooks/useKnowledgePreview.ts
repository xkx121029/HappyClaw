import type { App } from "antd";
import type { InputRef } from "antd/es/input";
import type { TFunction } from "i18next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  KnowledgeBase,
  KnowledgeDocument,
} from "../../../api/modules/knowledgeBases";
import { knowledgeBasesApi } from "../../../api/modules/knowledgeBases";
import { apiErrorMessage } from "../../../utils/apiError";
import { getDocKind, type DocKind } from "../../../utils/docKind";
import { saveBlobAsFile } from "../../../utils/saveBlobAsFile";
import { stripFrontmatter } from "../../../utils/markdown";
import {
  canDownloadKnowledgeOriginal,
  canPreviewKnowledgeDocument,
  canRichPreviewKnowledgeDocument,
  isEditableKnowledgeDocument,
  isKnowledgeMarkdownDocument,
} from "../../../utils/knowledgeDocPreview";
import {
  extractMarkdownOutline,
  stripMdInlineMarks,
  type MdOutlineItem,
} from "../mdOutline";
import styles from "../index.module.less";

type AppApi = ReturnType<typeof App.useApp>;

export interface UseKnowledgePreviewArgs {
  t: TFunction;
  message: AppApi["message"];
  selected: KnowledgeBase | null;
  documents: KnowledgeDocument[];
}

/** Document preview dialog: text/chunk loading, markdown outline and find bar. */
export function useKnowledgePreview({
  t,
  message,
  selected,
  documents,
}: UseKnowledgePreviewArgs) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewFilename, setPreviewFilename] = useState("");
  const [previewText, setPreviewText] = useState("");
  const [previewKind, setPreviewKind] = useState<DocKind | null>(null);
  const [previewDocId, setPreviewDocId] = useState<string | null>(null);
  const [previewHasOriginal, setPreviewHasOriginal] = useState(false);
  const [previewAsMarkdown, setPreviewAsMarkdown] = useState(false);
  const [previewMode, setPreviewMode] = useState<"file" | "chunks">("file");
  const [previewFileAvailable, setPreviewFileAvailable] = useState(true);
  const [chunkItems, setChunkItems] = useState<
    { ordinal: number; text: string }[]
  >([]);
  const [chunkLoading, setChunkLoading] = useState(false);
  const [chunkError, setChunkError] = useState<string | null>(null);
  const [previewMaximized, setPreviewMaximized] = useState(false);
  const [mdOutlineOpen, setMdOutlineOpen] = useState(true);
  const [mdActiveOutlineIndex, setMdActiveOutlineIndex] = useState(0);
  const [mdFindOpen, setMdFindOpen] = useState(false);
  const [mdFindQuery, setMdFindQuery] = useState("");
  const [mdFindIndex, setMdFindIndex] = useState(0);
  const [mdFindHitCount, setMdFindHitCount] = useState(0);
  const mdBodyRef = useRef<HTMLDivElement | null>(null);
  const mdFindInputRef = useRef<InputRef | null>(null);
  const mdFindHitsRef = useRef<{ node: Text; start: number }[]>([]);
  const previewTextAbortRef = useRef<AbortController | null>(null);
  const chunkRequestRef = useRef(0);
  const isRichPreview = Boolean(previewKind || previewAsMarkdown);

  const previewableDocs = useMemo(
    () =>
      documents.filter(
        (document) => !document.is_dir && canPreviewKnowledgeDocument(document),
      ),
    [documents],
  );
  const previewNavIndex = useMemo(
    () =>
      previewDocId
        ? previewableDocs.findIndex((document) => document.id === previewDocId)
        : -1,
    [previewDocId, previewableDocs],
  );

  const mdOutlineItems = useMemo(
    () =>
      previewAsMarkdown && previewText.trim()
        ? extractMarkdownOutline(stripFrontmatter(previewText))
        : [],
    [previewAsMarkdown, previewText],
  );

  type MdFindHit = { node: Text; start: number };

  const collectMdFindHits = useCallback((host: HTMLElement, q: string) => {
    const needle = q.trim().toLowerCase();
    if (!needle) return [] as MdFindHit[];
    const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
    const hits: MdFindHit[] = [];
    let node = walker.nextNode();
    while (node) {
      const text = node.textContent ?? "";
      const lower = text.toLowerCase();
      let from = 0;
      while (from < lower.length) {
        const at = lower.indexOf(needle, from);
        if (at < 0) break;
        hits.push({ node: node as Text, start: at });
        from = at + Math.max(1, needle.length);
      }
      node = walker.nextNode();
    }
    return hits;
  }, []);

  // Count + jump both use the rendered DOM so the counter stays honest.
  useEffect(() => {
    if (!mdFindOpen || !previewAsMarkdown || previewLoading) {
      mdFindHitsRef.current = [];
      setMdFindHitCount(0);
      return;
    }
    const q = mdFindQuery.trim();
    if (!q) {
      mdFindHitsRef.current = [];
      setMdFindHitCount(0);
      setMdFindIndex(0);
      return;
    }
    let cancelled = false;
    const sync = () => {
      if (cancelled) return;
      const host = mdBodyRef.current;
      if (!host) {
        mdFindHitsRef.current = [];
        setMdFindHitCount(0);
        return;
      }
      const hits = collectMdFindHits(host, q);
      mdFindHitsRef.current = hits;
      setMdFindHitCount(hits.length);
      setMdFindIndex((prev) =>
        hits.length === 0 ? 0 : Math.min(prev, hits.length - 1),
      );
    };
    const raf = window.requestAnimationFrame(sync);
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(raf);
    };
  }, [
    mdFindOpen,
    mdFindQuery,
    previewAsMarkdown,
    previewText,
    previewLoading,
    collectMdFindHits,
  ]);

  const scrollToMdHeading = useCallback((item: MdOutlineItem) => {
    const host = mdBodyRef.current;
    if (!host) return;
    const headings = Array.from(host.querySelectorAll("h1,h2,h3,h4,h5,h6")).map(
      (heading) => ({
        el: heading,
        text: stripMdInlineMarks(heading.textContent ?? ""),
      }),
    );
    const byOccurrence = headings.filter((h) => h.text === item.title);
    const target =
      byOccurrence[item.occurrence] ??
      byOccurrence[0] ??
      // Titles containing escaped code spans can differ from the rendered
      // heading text — fall back to a prefix match.
      headings.find((h) => h.text.startsWith(item.title.slice(0, 8)));
    target?.el.scrollIntoView({ behavior: "auto", block: "start" });
  }, []);

  // Markdown outline scroll-spy: highlight the last heading above the fold.
  useEffect(() => {
    if (!previewAsMarkdown || mdOutlineItems.length === 0) {
      setMdActiveOutlineIndex(0);
      return;
    }
    const host = mdBodyRef.current;
    if (!host) return;
    const update = () => {
      const headings = Array.from(
        host.querySelectorAll<HTMLElement>("h1,h2,h3,h4,h5,h6"),
      );
      if (headings.length === 0) return;
      const top = host.scrollTop + 12;
      let active = 0;
      for (let i = 0; i < headings.length; i += 1) {
        if (headings[i].offsetTop <= top) active = i;
        else break;
      }
      setMdActiveOutlineIndex(Math.min(active, mdOutlineItems.length - 1));
    };
    update();
    host.addEventListener("scroll", update, { passive: true });
    return () => host.removeEventListener("scroll", update);
  }, [previewAsMarkdown, previewText, mdOutlineItems.length]);

  const jumpMdFind = useCallback(
    (direction: 1 | -1) => {
      const host = mdBodyRef.current;
      const q = mdFindQuery.trim();
      if (!host || !q) return;
      const hits = collectMdFindHits(host, q);
      mdFindHitsRef.current = hits;
      setMdFindHitCount(hits.length);
      if (hits.length === 0) {
        setMdFindIndex(0);
        return;
      }
      const next =
        (((mdFindIndex + direction) % hits.length) + hits.length) % hits.length;
      setMdFindIndex(next);
      const hit = hits[next];
      const el = hit.node.parentElement;
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      try {
        const range = document.createRange();
        const end = Math.min(
          hit.start + q.length,
          hit.node.textContent?.length ?? hit.start,
        );
        range.setStart(hit.node, hit.start);
        range.setEnd(hit.node, end);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
      } catch {
        /* ignore selection failures in odd text nodes */
      }
      el.classList.add(styles.mdFindFlash);
      window.setTimeout(() => el.classList.remove(styles.mdFindFlash), 900);
    },
    [mdFindIndex, mdFindQuery, collectMdFindHits],
  );

  const closePreview = useCallback(() => {
    previewTextAbortRef.current?.abort();
    previewTextAbortRef.current = null;
    setPreviewOpen(false);
    setPreviewKind(null);
    setPreviewDocId(null);
    setPreviewHasOriginal(false);
    setPreviewAsMarkdown(false);
    setPreviewMode("file");
    setPreviewFileAvailable(true);
    chunkRequestRef.current += 1;
    setChunkItems([]);
    setChunkLoading(false);
    setChunkError(null);
    setPreviewMaximized(false);
    setMdOutlineOpen(true);
    setMdFindOpen(false);
    setMdFindQuery("");
    setMdFindIndex(0);
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
    }
  }, []);

  const requestClosePreview = useCallback(() => {
    // Esc / mask: exit CSS maximized first, then close (native FS Esc is
    // handled by the browser before the dialog sees it).
    if (previewMaximized && !document.fullscreenElement) {
      setPreviewMaximized(false);
      return;
    }
    closePreview();
  }, [closePreview, previewMaximized]);

  /**
   * Native fullscreen on the document content area (viewer toolbar + PDF /
   * bookmarks) — no dialog chrome around it; the browser's own "press Esc to
   * exit" hint covers leaving. Falls back to the CSS maximized dialog when
   * the Fullscreen API is unavailable or rejected (e.g. embedded contexts).
   */
  const togglePreviewFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
      return;
    }
    if (previewMaximized) {
      // CSS-fallback maximized — restore the regular dialog.
      setPreviewMaximized(false);
      return;
    }
    const fsEl = (document.querySelector<HTMLElement>(
      "[data-preview-fullscreen-root]",
    ) ?? document.querySelector<HTMLElement>(".happyclaw-modal-content")) as
      | (HTMLElement & {
          webkitRequestFullscreen?: () => Promise<void> | void;
        })
      | null;
    const request =
      fsEl?.requestFullscreen?.bind(fsEl) ?? fsEl?.webkitRequestFullscreen;
    if (!fsEl || !request) {
      setPreviewMaximized(true);
      return;
    }
    void Promise.resolve(request.call(fsEl)).then(
      () => {
        // fullscreenchange flips previewMaximized on success.
      },
      () => setPreviewMaximized(true),
    );
  }, [previewMaximized]);

  // Keep the button state in sync when the browser exits fullscreen (Esc).
  useEffect(() => {
    if (!previewOpen) return;
    const sync = () => setPreviewMaximized(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", sync);
    document.addEventListener("webkitfullscreenchange", sync);
    return () => {
      document.removeEventListener("fullscreenchange", sync);
      document.removeEventListener("webkitfullscreenchange", sync);
    };
  }, [previewOpen]);

  // Cmd/Ctrl+F opens the markdown find bar while the preview is open.
  useEffect(() => {
    if (!previewOpen || !previewAsMarkdown) return;
    const onKey = (event: KeyboardEvent) => {
      if (
        !(event.metaKey || event.ctrlKey) ||
        event.key.toLowerCase() !== "f"
      ) {
        return;
      }
      event.preventDefault();
      setMdFindOpen(true);
      window.setTimeout(() => mdFindInputRef.current?.focus(), 0);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [previewOpen, previewAsMarkdown]);

  const loadDocumentChunks = async (kbId: string, documentId: string) => {
    const request = ++chunkRequestRef.current;
    setChunkLoading(true);
    setChunkError(null);
    try {
      const body = await knowledgeBasesApi.listDocumentChunks(kbId, documentId);
      if (chunkRequestRef.current !== request) return;
      setChunkItems(body.chunks);
    } catch (error) {
      if (chunkRequestRef.current !== request) return;
      setChunkItems([]);
      setChunkError(
        apiErrorMessage(error, t("knowledgeBases.chunksFailed"), t),
      );
    } finally {
      if (chunkRequestRef.current === request) setChunkLoading(false);
    }
  };

  const openDocumentPreview = async (
    document: KnowledgeDocument,
    mode: "file" | "chunks" = "file",
  ) => {
    if (!selected || document.is_dir) return;
    const filePreview = canPreviewKnowledgeDocument(document);
    const chunkPreview = (document.chunk_count ?? 0) > 0;
    if (mode === "file" && !filePreview) return;
    if (!filePreview && !chunkPreview) return;
    const rich = canRichPreviewKnowledgeDocument(document);
    const kind = rich ? getDocKind(document.filename) : null;
    const asMarkdown = isKnowledgeMarkdownDocument(document);
    previewTextAbortRef.current?.abort();
    const abort = new AbortController();
    previewTextAbortRef.current = abort;
    setPreviewOpen(true);
    setPreviewFilename(document.filename);
    setPreviewKind(kind);
    setPreviewDocId(document.id);
    setPreviewHasOriginal(canDownloadKnowledgeOriginal(document));
    setPreviewAsMarkdown(asMarkdown);
    setPreviewText("");
    setMdOutlineOpen(true);
    setMdActiveOutlineIndex(0);
    setMdFindOpen(false);
    setMdFindQuery("");
    setMdFindIndex(0);
    setMdFindHitCount(0);
    setPreviewFileAvailable(filePreview);
    setPreviewMode(filePreview ? mode : "chunks");
    setChunkItems([]);
    setChunkError(null);
    if (mode === "chunks" || !filePreview) {
      void loadDocumentChunks(selected.id, document.id);
    }
    if (!filePreview) {
      setPreviewLoading(false);
      setPreviewText("");
      return;
    }
    if (kind) {
      setPreviewLoading(false);
      return;
    }
    setPreviewLoading(true);
    try {
      // Prefer raw UTF-8 for editable text so markdown preview matches the file.
      if (asMarkdown || isEditableKnowledgeDocument(document)) {
        const payload = await knowledgeBasesApi.getTextDocument(
          selected.id,
          document.id,
        );
        if (abort.signal.aborted) return;
        setPreviewFilename(payload.filename);
        setPreviewText(
          payload.text.trim() ? payload.text : t("knowledgeBases.previewEmpty"),
        );
      } else {
        const preview = await knowledgeBasesApi.previewDocument(
          selected.id,
          document.id,
        );
        if (abort.signal.aborted) return;
        setPreviewFilename(preview.filename);
        setPreviewText(
          preview.text.trim() ? preview.text : t("knowledgeBases.previewEmpty"),
        );
      }
    } catch (error) {
      if (abort.signal.aborted) return;
      setPreviewOpen(false);
      message.error(
        apiErrorMessage(error, t("knowledgeBases.previewFailed"), t),
      );
    } finally {
      if (!abort.signal.aborted) setPreviewLoading(false);
    }
  };

  const downloadDocumentOriginal = async (
    documentId: string,
    filename: string,
  ) => {
    if (!selected) return;
    try {
      const blob = await knowledgeBasesApi.fetchDocumentFile(
        selected.id,
        documentId,
        "attachment",
      );
      await saveBlobAsFile(blob, filename || "download");
    } catch (error) {
      message.error(
        apiErrorMessage(error, t("knowledgeBases.downloadOriginalFailed"), t),
      );
    }
  };

  // Depend on selected.id (not the whole selected object). Silent indexing
  // polls call setSelected(base) every 2.5s with a new object reference; that
  // used to recreate fetchBlob and re-run DocumentPreviewCore's load effect,
  // aborting slow Office parsers (docx/pptx/xlsx) while fast PDF survived.
  const selectedId = selected?.id;
  const fetchPreviewBlob = useCallback(
    async (
      onProgress?: (loaded: number, total: number) => void,
      signal?: AbortSignal,
    ) => {
      if (!selectedId || !previewDocId) {
        throw new Error("missing knowledge document preview target");
      }
      return knowledgeBasesApi.fetchDocumentFile(
        selectedId,
        previewDocId,
        "inline",
        onProgress,
        signal,
      );
    },
    [selectedId, previewDocId],
  );
  return {
    previewOpen,
    setPreviewOpen,
    previewLoading,
    previewFilename,
    setPreviewFilename,
    previewText,
    previewKind,
    previewDocId,
    previewHasOriginal,
    previewAsMarkdown,
    previewMode,
    setPreviewMode,
    previewFileAvailable,
    chunkItems,
    chunkLoading,
    chunkError,
    previewMaximized,
    mdOutlineOpen,
    setMdOutlineOpen,
    mdActiveOutlineIndex,
    mdFindOpen,
    setMdFindOpen,
    mdFindQuery,
    setMdFindQuery,
    mdFindIndex,
    setMdFindIndex,
    mdFindHitCount,
    mdBodyRef,
    mdFindInputRef,
    isRichPreview,
    previewableDocs,
    previewNavIndex,
    mdOutlineItems,
    scrollToMdHeading,
    jumpMdFind,
    closePreview,
    requestClosePreview,
    togglePreviewFullscreen,
    loadDocumentChunks,
    openDocumentPreview,
    downloadDocumentOriginal,
    fetchPreviewBlob,
  };
}
