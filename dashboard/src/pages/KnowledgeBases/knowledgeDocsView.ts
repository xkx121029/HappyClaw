export type DocsViewMode = "card" | "table";

export const DOCS_VIEW_STORAGE_KEY = "octop:knowledge-bases-docs-view";

export function loadDocsViewMode(): DocsViewMode {
  const stored = localStorage.getItem(DOCS_VIEW_STORAGE_KEY);
  return stored === "table" ? "table" : "card";
}
