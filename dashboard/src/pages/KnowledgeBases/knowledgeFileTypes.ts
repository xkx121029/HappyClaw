import type { KnowledgeDocument } from "../../api/modules/knowledgeBases";

/** Document types accepted without OCR. */
export const BASE_DOCUMENT_TYPES =
  ".md,.markdown,.txt,.rst,.html,.htm,.json,.jsonl,.yaml,.yml,.csv,.tsv,.pdf,.doc,.wps,.docx,.pptx,.xls,.xlsx,.xlsm";
/** Image types accepted once OCR is enabled. */
export const OCR_DOCUMENT_TYPES = ".png,.jpg,.jpeg,.webp";

/** Match ``<input accept>`` extension tokens (e.g. ``.pdf,.docx``). */
export function fileMatchesAccept(file: File, acceptCsv: string): boolean {
  const tokens = acceptCsv
    .split(",")
    .map((token) => token.trim().toLowerCase())
    .filter(Boolean);
  if (tokens.length === 0) return true;
  const name = file.name.toLowerCase();
  return tokens.some((token) =>
    token.startsWith(".") ? name.endsWith(token) : false,
  );
}

export function fileExtensionLabel(filename: string): string {
  const ext = filename.includes(".")
    ? filename.slice(filename.lastIndexOf(".") + 1)
    : "";
  return ext.trim().toUpperCase().slice(0, 5);
}

/** Indexing status of a document → antd tag color. */
export function documentStatusColor(status: KnowledgeDocument["status"]) {
  if (status === "ready") return "success";
  if (status === "failed") return "error";
  if (status === "processing") return "processing";
  return "default";
}
