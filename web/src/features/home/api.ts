import { api } from "@/lib/api/client";
import { isThread } from "@/features/chat/types";
import type { Agent } from "@/features/chat/types";

import type {
  HomeThread,
  PendingApproval,
  PendingApprovalRaw,
  RuntimeActivity,
  UsageSummary,
} from "./types";

type Raw = Record<string, unknown>;

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

export async function getActivity(): Promise<RuntimeActivity> {
  const { data } = await api.GET("/api/runtime/activity");
  const body = (data ?? {}) as Raw;
  return {
    busy: Boolean(body.busy),
    active_turns: num(body.active_turns),
    dashboard_connections: num(body.dashboard_connections),
    terminal_sessions: num(body.terminal_sessions),
    running_agents: num(body.running_agents),
    running_jobs: num(body.running_jobs),
    threads_with_subscribers: num(body.threads_with_subscribers),
    updated_at: num(body.updated_at),
  };
}

export async function getUsage(): Promise<UsageSummary> {
  const { data } = await api.GET("/api/usage/summary", {
    params: { query: { window: "last_30d", granularity: "by_day" } },
  });
  const body = (data ?? {}) as Raw;
  return {
    range_start: num(body.range_start),
    range_end: num(body.range_end),
    total_tokens: num(body.total_tokens),
    input_tokens: num(body.input_tokens),
    output_tokens: num(body.output_tokens),
    model_calls: num(body.model_calls),
    turns: num(body.turns),
    cache_hit_percent: num(body.cache_hit_percent),
  };
}

export async function listHomeAgents(): Promise<Agent[]> {
  const { data } = await api.GET("/api/agents", { params: { query: { scope: "mine" } } });
  const rows: unknown[] = Array.isArray(data) ? data : [];
  return rows.filter(
    (row): row is Agent =>
      typeof row === "object" &&
      row !== null &&
      typeof (row as Agent).agent_id === "string" &&
      typeof (row as Agent).name === "string",
  );
}

/** Pending questions/approvals for one agent, flattened to what the inbox shows. */
export async function getPendingApprovals(agentId: string): Promise<PendingApproval[]> {
  const { data } = await api.GET("/api/agents/{agent_id}/chat/hitl/pending", {
    params: { path: { agent_id: agentId } },
  });
  const items = (data as { items?: unknown } | undefined)?.items;
  if (!Array.isArray(items)) return [];
  return items.flatMap((item): PendingApproval[] => {
    if (typeof item !== "object" || item === null) return [];
    const row = item as PendingApprovalRaw;
    if (typeof row.pendingId !== "string" || typeof row.agentId !== "string") return [];
    return [
      {
        pendingId: row.pendingId,
        agentId: row.agentId,
        threadId: typeof row.threadId === "string" ? row.threadId : "",
        sessionTitle: str(row.sessionTitle),
        kind: row.isAsk === false ? "approval" : "question",
      },
    ];
  });
}

export async function getRecentThreads(
  agent: Agent,
  limit = 4,
): Promise<HomeThread[]> {
  const { data } = await api.GET("/api/agents/{agent_id}/threads", {
    params: { path: { agent_id: agent.agent_id }, query: { limit } },
  });
  const rows: unknown[] = Array.isArray(data) ? data : [];
  return rows.filter(isThread).map((thread) => ({
    thread_id: thread.thread_id,
    title: thread.title,
    agentId: agent.agent_id,
    agentName: agent.name,
    timestamp: thread.last_active || thread.created_at,
    hasMessages: Boolean(thread.has_messages),
  }));
}
