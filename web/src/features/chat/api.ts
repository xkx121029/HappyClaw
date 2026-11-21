import { api } from "@/lib/api/client";

import {
  isAgent,
  isThread,
  type Agent,
  type Thread,
  type ThreadHistory,
} from "./types";

export async function listAgents(): Promise<Agent[]> {
  const data = await api.GET("/api/agents", { params: { query: { scope: "mine" } } });
  const rows: unknown[] = Array.isArray(data.data) ? data.data : [];
  return rows.filter(isAgent);
}

export async function listThreads(agentId: string, limit = 50): Promise<Thread[]> {
  const data = await api.GET("/api/agents/{agent_id}/threads", {
    params: {
      path: { agent_id: agentId },
      query: { limit },
    },
  });
  const rows: unknown[] = Array.isArray(data.data) ? data.data : [];
  return rows
    .filter(isThread)
    .sort(
      (left, right) =>
        (right.last_active || right.created_at) - (left.last_active || left.created_at),
    );
}

export async function getHistory(
  agentId: string,
  threadId: string,
  limit = 100,
): Promise<ThreadHistory> {
  const data = await api.GET("/api/agents/{agent_id}/threads/{thread_id}/history", {
    params: {
      path: { agent_id: agentId, thread_id: threadId },
      query: { limit, offset: 0 },
    },
  });
  const body = (data.data ?? {}) as Partial<ThreadHistory>;
  return {
    thread_id: body.thread_id ?? threadId,
    messages: Array.isArray(body.messages) ? body.messages : [],
    has_more: body.has_more,
    next_cursor: body.next_cursor ?? null,
    turn_active: body.turn_active,
  };
}

export async function createThread(agentId: string): Promise<{ thread_id: string }> {
  const data = await api.POST("/api/agents/{agent_id}/threads", {
    params: { path: { agent_id: agentId } },
  });
  const threadId = (data.data as { thread_id?: string } | undefined)?.thread_id;
  if (!threadId) throw new Error("The backend did not return a thread id");
  return { thread_id: threadId };
}
