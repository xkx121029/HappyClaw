/**
 * Home payloads. Like the chat routes, these endpoints return untyped dicts, so
 * the fields the page reads are declared here and narrowed in `api.ts`.
 */

export interface RuntimeActivity {
  busy: boolean;
  active_turns: number;
  dashboard_connections: number;
  terminal_sessions: number;
  running_agents: number;
  running_jobs: number;
  threads_with_subscribers: number;
  updated_at: number;
}

export interface UsageSummary {
  range_start: number;
  range_end: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  model_calls: number;
  turns: number;
  cache_hit_percent: number;
}

export interface PendingApproval {
  pendingId: string;
  agentId: string;
  threadId: string;
  sessionTitle: string | null;
  kind: "question" | "approval";
  createdAt?: number;
}

/** Raw HITL row, as the endpoint returns it (dict, not a typed model). */
export interface PendingApprovalRaw {
  pendingId?: unknown;
  agentId?: unknown;
  threadId?: unknown;
  sessionTitle?: unknown;
  isAsk?: unknown;
}

export interface HomeThread {
  thread_id: string;
  title: string | null;
  agentId: string;
  agentName: string;
  timestamp: number;
  hasMessages: boolean;
}
