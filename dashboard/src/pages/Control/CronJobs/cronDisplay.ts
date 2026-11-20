/** Helpers to map Octop cron rows for dashboard display. */

import { formatServerDateTime } from "../../../utils/formatMessageTime";

export function channelFromSessionKey(sessionKey: string): string {
  const parts = sessionKey.split(":");
  return parts.length >= 2 ? parts[1] : "dashboard";
}

export function formatCronTimestamp(
  ts: number | null | undefined,
  timeZone?: string,
): string {
  if (!ts) return "—";
  return formatServerDateTime(ts, timeZone);
}

export function extractPromptFromJob(job: {
  task_type?: string;
  text?: string;
  request?: { input?: unknown };
}): string {
  if (job.task_type === "text" && job.text) return job.text;
  const input = job.request?.input;
  if (Array.isArray(input) && input.length > 0) {
    const last = input[input.length - 1] as
      | { content?: Array<{ type: string; text: string }> }
      | undefined;
    const part = last?.content?.find?.((c) => c.type === "text");
    if (part?.text) return part.text;
  }
  if (typeof input === "string") return input;
  return "";
}

/** Short preview for tables and lists (full text via tooltip elsewhere). */
export function truncatePromptPreview(text: string, maxLen = 48): string {
  const trimmed = text.trim();
  if (trimmed.length <= maxLen) return trimmed;
  return `${trimmed.slice(0, maxLen)}…`;
}

/** Known run failure causes; the drawer renders them with localized copy. */
export type CronRunErrorKind =
  | "missed"
  | "noModel"
  | "agentNotFound"
  | "agentNotRunning"
  | "agentBusy"
  | "interactionRequired"
  | "emptyResponse"
  | "alreadyRunning"
  | "leaseLost"
  | "cancelled"
  | "gatewayNotReady"
  | "timeout";

// Backend cron/agent errors are stable English literals; match them in order of
// specificity. The raw text stays available in the row tooltip.
const RUN_ERROR_PATTERNS: Array<[CronRunErrorKind, RegExp]> = [
  ["noModel", /has no model configured/i],
  ["agentNotFound", /agent .* not found/i],
  ["agentNotRunning", /not running|expert is disabled/i],
  ["agentBusy", /\bis busy\b/i],
  ["interactionRequired", /requires user interaction/i],
  ["emptyResponse", /produced no visible response/i],
  ["alreadyRunning", /another run was already in progress/i],
  ["leaseLost", /run lease .*\b(unavailable|lost)\b/i],
  ["cancelled", /server is shutting down/i],
  ["gatewayNotReady", /gateway is not ready/i],
  ["timeout", /\btimed? ?out\b|\btimeout\b/i],
];

/** Classify a run row so the UI can show a localized reason. */
export function classifyCronRunError(run: {
  status: string;
  error?: string | null;
}): CronRunErrorKind | "unknown" {
  if (run.status === "missed") return "missed";
  const text = (run.error ?? "").trim();
  if (!text) return "unknown";
  for (const [kind, pattern] of RUN_ERROR_PATTERNS) {
    if (pattern.test(text)) return kind;
  }
  return "unknown";
}

