import type { BaoTask, BaoTaskStatus } from "../../api/modules/bao";

/** UI model for one dispatch. Populated from the server ledger, never storage. */
export interface BaoTaskRecord {
  id: string;
  agentId: string;
  agentName: string;
  threadId: string;
  sessionTitle: string;
  projectKey: string;
  projectName: string;
  text: string;
  dispatchedAt: number;
  status: BaoTaskStatus;
  sawActive: boolean;
  resultText?: string;
  errorText?: string;
  updatedAt: number;
  /** Bao created the conversation as part of this dispatch. */
  created?: boolean;
  /** Why Bao routed here; rendered on the page's decision card. */
  routeReason?: { code: string; params: Record<string, string | number> };
  /** How many automatic nudges Bao sent before the turn finished. */
  followupCount?: number;
  evalStatus?: string | null;
}

const LEGACY_STORAGE_KEY = "octop:bao:tasks:v1";

export function fromServerTask(row: BaoTask): BaoTaskRecord {
  return {
    id: row.id,
    agentId: row.agent_id,
    agentName: row.agent_name,
    threadId: row.thread_id,
    sessionTitle: row.session_title,
    projectKey: row.project_key,
    projectName: row.project_name,
    text: row.task_text,
    dispatchedAt: row.dispatched_at,
    status: row.status,
    sawActive: false,
    resultText: row.result_text ?? undefined,
    errorText: row.error_text ?? undefined,
    updatedAt: row.updated_at,
    routeReason: row.route_reason?.code ? row.route_reason : undefined,
    followupCount: row.followup_count ?? 0,
    evalStatus: row.eval_status ?? null,
  };
}

/**
 * Read the pre-upgrade browser ledger once. The records are POSTed to
 * ``/bao/tasks/import`` and the key is removed only after the server accepts
 * them, so an upgrade never silently drops dispatch history.
 */
export function loadLegacyTasks(): Record<string, unknown>[] {
  try {
    const raw = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (row): row is Record<string, unknown> =>
        Boolean(row) && typeof row === "object" && !Array.isArray(row),
    );
  } catch {
    return [];
  }
}

export function clearLegacyTasks(): void {
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // Private browsing / quota limits must not break page load.
  }
}
