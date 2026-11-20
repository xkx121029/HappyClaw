import type { OctopThreadHistory } from "../../api/modules/octopThreads";
import type { BaoOverview, BaoProject, BaoSession } from "../../api/modules/bao";
import { extractText } from "../../utils/messageParser";

export type BaoScope = "global" | "project";

export interface BaoSessionRef {
  project: BaoProject;
  session: BaoSession;
}

/** ``/chat/<agentId>`` or ``/chat/<agentId>/<threadId>`` → agent id. */
export function agentIdFromPath(pathname: string): string | null {
  const match = /^\/chat\/([^/?#]+)/.exec(pathname);
  return match ? decodeURIComponent(match[1]) : null;
}

export function findProject(
  overview: BaoOverview | null,
  key: string | null,
): BaoProject | null {
  if (!overview || !key) return null;
  return overview.projects.find((project) => project.key === key) ?? null;
}

/** Project key that owns the agent shown on the current route, if any. */
export function projectKeyForAgent(
  overview: BaoOverview | null,
  agentId: string | null,
): string | null {
  if (!overview || !agentId) return null;
  for (const project of overview.projects) {
    if (project.agents.some((agent) => agent.agent_id === agentId)) {
      return project.key;
    }
  }
  return null;
}

/**
 * Default scope for the panel: a project page means project scope, everything
 * else starts global. Once the user switches, the panel keeps their choice
 * until it is reopened.
 */
export function inferScope(
  overview: BaoOverview | null,
  pathname: string,
): { scope: BaoScope; projectKey: string | null } {
  const projectKey = projectKeyForAgent(overview, agentIdFromPath(pathname));
  return projectKey
    ? { scope: "project", projectKey }
    : { scope: "global", projectKey: null };
}

export function collectSessions(projects: BaoProject[]): BaoSessionRef[] {
  return projects.flatMap((project) =>
    project.sessions.map((session) => ({ project, session })),
  );
}

/**
 * Roving-tabindex helper for keyboard navigation inside the session list.
 * Returns ``null`` for keys the list does not handle.
 */
export function nextFocusIndex(
  current: number,
  total: number,
  key: string,
): number | null {
  if (total <= 0) return null;
  if (key === "Home") return 0;
  if (key === "End") return total - 1;
  if (key === "ArrowDown") return Math.min(Math.max(current, 0) + 1, total - 1);
  if (key === "ArrowUp") return Math.max(current - 1, 0);
  return null;
}

export function findSessionRef(
  overview: BaoOverview | null,
  threadId: string | null,
): BaoSessionRef | null {
  if (!overview || !threadId) return null;
  return (
    collectSessions(overview.projects).find(
      (ref) => ref.session.thread_id === threadId,
    ) ?? null
  );
}

export type BaoTaskStatus = "running" | "awaiting" | "done" | "failed";

export interface BaoTaskOutcome {
  status: BaoTaskStatus;
  resultText?: string;
  errorText?: string;
  /** Sticky flag: once a turn was seen running, a later idle thread is settled. */
  sawActive: boolean;
}

function isFailure(message: OctopThreadHistory["messages"][number]): boolean {
  if (message.error_code) return true;
  const status = (message.status ?? "").toLowerCase();
  return status === "error" || status === "failed";
}

const SETTLE_SLACK_SECONDS = 5;
const RESULT_MAX_CHARS = 600;

/** History timestamps are milliseconds, thread timestamps are seconds. */
function toSeconds(timestamp: number): number {
  return timestamp > 1e12 ? timestamp / 1000 : timestamp;
}

function lastAssistant(
  history: OctopThreadHistory,
): OctopThreadHistory["messages"][number] | null {
  for (let i = history.messages.length - 1; i >= 0; i -= 1) {
    if (history.messages[i].role === "assistant") return history.messages[i];
  }
  return null;
}

function clip(text: string): string {
  const trimmed = text.trim();
  return trimmed.length > RESULT_MAX_CHARS
    ? `${trimmed.slice(0, RESULT_MAX_CHARS)}…`
    : trimmed;
}

/**
 * Turn a thread history snapshot into a dispatch status.
 *
 * A stale assistant message (older than the dispatch) must not be reported as
 * this task's result; otherwise the panel would show yesterday's answer the
 * moment a task is submitted.
 */
export function resolveDispatchOutcome(
  history: OctopThreadHistory,
  dispatchedAt: number,
  sawActive: boolean,
): BaoTaskOutcome {
  if (history.hitl_pending) {
    return { status: "awaiting", sawActive: sawActive || history.turn_active === true };
  }
  if (history.turn_active) {
    return { status: "running", sawActive: true };
  }
  const assistant = lastAssistant(history);
  const fresh = assistant
    ? toSeconds(Number(assistant.timestamp ?? 0)) >=
      dispatchedAt - SETTLE_SLACK_SECONDS
    : false;
  if (!assistant || !fresh) {
    // No reply for this task yet. Keep polling rather than declaring success.
    return { status: "running", sawActive };
  }
  const text = clip(extractText(assistant.content));
  if (isFailure(assistant)) {
    return {
      status: "failed",
      errorText: text || assistant.error_code || undefined,
      sawActive,
    };
  }
  return { status: "done", resultText: text, sawActive };
}
