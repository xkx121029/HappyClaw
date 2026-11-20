import { request } from "../request";

/** A project (workspace folder) and its agents as reported by the backend. */
export interface BaoAgent {
  agent_id: string;
  name: string;
  state: string;
  last_error: string | null;
  model_ready: boolean;
  /** False for team members: they have no runtime of their own. */
  direct_dispatchable?: boolean;
  direct_dispatch_hint?: "team_member" | null;
  team_name?: string | null;
}

export interface BaoSession {
  agent_id: string;
  agent_name: string;
  thread_id: string;
  title: string | null;
  last_active: number;
  created_at: number;
  turn_active: boolean;
  awaiting_user: boolean;
  contributed: boolean;
}

export interface BaoProject {
  key: string;
  name: string;
  is_default: boolean;
  workspace_dir: string;
  agents: BaoAgent[];
  sessions: BaoSession[];
  running_agents: number;
  active_turns: number;
  awaiting_user: number;
  failed_agents: number;
}

export interface BaoOverview {
  updated_at: number;
  projects: BaoProject[];
  totals: {
    projects: number;
    agents: number;
    running_agents: number;
    active_turns: number;
    awaiting_user: number;
    failed_agents: number;
  };
}

export interface BaoDispatchResult {
  dispatched: true;
  /** True when Bao created the conversation as part of this dispatch. */
  created: boolean;
  agent_id: string;
  agent_name: string;
  thread_id: string;
  session_title: string | null;
  project_key: string;
  project_name: string;
  dispatched_at: number;
  task_id: string;
  task: BaoTask;
}

export type BaoTaskStatus = "running" | "awaiting" | "done" | "failed";

/** One persisted dispatch record, owned by the server. */
export interface BaoTask {
  id: string;
  agent_id: string;
  agent_name: string;
  thread_id: string;
  session_title: string;
  project_key: string;
  project_name: string;
  task_text: string;
  source: string;
  route_reason: { code: string; params: Record<string, string | number> } | null;
  status: BaoTaskStatus;
  result_text: string | null;
  error_text: string | null;
  created_at: number;
  dispatched_at: number;
  updated_at: number;
  completed_at: number | null;
  acknowledged_at: number | null;
  followup_count?: number;
  last_followup_at?: number | null;
  eval_status?: string | null;
}

export type BaoChatRole = "user" | "bao";

/** One turn of the conversation Bao keeps with the user across dispatches. */
export interface BaoChatMessage {
  id: string;
  role: BaoChatRole;
  text: string;
  intent: string;
  refs: Record<string, unknown>;
  task_id: string | null;
  created_at: number;
}

export interface BaoSettings {
  name: string;
  proactive_muted: boolean;
  identity_set: boolean;
  onboarding_done: boolean;
  /** Mascot engine body id (see ``MASCOT_SHAPES``). */
  shape: string;
  /** Mascot engine ink id (see ``MASCOT_INKS``). */
  color: string;
  /** Custom body colour (``#rrggbb``), or null to use the ink palette. */
  body_color: string | null;
  /** Custom eye colour (``#rrggbb``), or null for the cut-out look. */
  eye_color: string | null;
  /** Paint the body with the live theme accent instead of an ink. */
  follow_theme: boolean;
}

export interface BaoChatResponse {
  intent: string;
  reply_code: string;
  reply_params: Record<string, string | number>;
  reply_text: string;
  messages: BaoChatMessage[];
  task: BaoTask | null;
  settings: BaoSettings;
  needs_target?: boolean;
  candidates?: BaoRouteDecision["candidates"];
  decision?: BaoRouteDecision;
  tasks?: BaoTask[];
  dispatch?: BaoDispatchResult;
}

export interface BaoChatHistory {
  updated_at: number;
  messages: BaoChatMessage[];
  settings: BaoSettings;
}

export interface BaoTasksResponse {
  updated_at: number;
  tasks: BaoTask[];
  retention: { max_per_user: number; max_age_days: number };
}

export interface BaoTaskImportResult {
  imported: number;
  skipped: number;
  updated_at: number;
}

export interface BaoRouteProjectRef {
  key: string;
  name: string;
  is_default: boolean;
}

export interface BaoRouteAgentRef {
  agent_id: string;
  name: string;
  state: string;
  model_ready: boolean;
  project_key?: string;
  project_name?: string;
  direct_dispatchable?: boolean;
  direct_dispatch_hint?: "team_member" | null;
  team_name?: string | null;
}

export interface BaoRouteSessionRef {
  agent_id: string;
  agent_name: string;
  thread_id: string;
  title: string | null;
  last_active: number;
  turn_active: boolean;
  awaiting_user: boolean;
}

/** Bao's routing decision: where a task goes and why. */
export interface BaoRouteDecision {
  decided: boolean;
  needs_target: boolean;
  reason: { code: string; params: Record<string, string | number> };
  project?: BaoRouteProjectRef;
  agent?: BaoRouteAgentRef;
  thread?: BaoRouteSessionRef | null;
  create_thread?: boolean;
  direct_dispatchable?: boolean;
  blocked?: "team_member";
  model_attempt?: { tried: boolean; code: string; detail: string };
  candidates?: {
    projects: BaoRouteProjectRef[];
    agents: BaoRouteAgentRef[];
    sessions: BaoRouteSessionRef[];
  };
}

export const baoApi = {
  overview: (sessionLimit = 20) =>
    request<BaoOverview>(`/bao/overview?session_limit=${sessionLimit}`),

  /** Bao decides the destination; dispatch still uses the normal chat pipeline. */
  route: (body: {
    text: string;
    scope: "global" | "project";
    project_key?: string | null;
  }) =>
    request<BaoRouteDecision>("/bao/route", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** ``thread_id: null`` lets the backend create a fresh conversation. */
  dispatch: (body: {
    agent_id: string;
    thread_id?: string | null;
    text: string;
    route_reason?: { code: string; params: Record<string, string | number> };
    source?: string;
  }) =>
    request<BaoDispatchResult>("/bao/dispatch", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Server-side ledger; ``ack=false`` keeps unread counts for the Home inbox. */
  tasks: (limit = 50, ack = true) =>
    request<BaoTasksResponse>(`/bao/tasks?limit=${limit}&ack=${ack}`),

  /** Explicit read only — opening a page must not swallow unread results. */
  ackTasks: (ids: string[]) =>
    request<{ ok: boolean; acknowledged: number }>("/bao/tasks/ack", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),

  /** One-time migration of pre-upgrade browser records. */
  importTasks: (tasks: unknown[]) =>
    request<BaoTaskImportResult>("/bao/tasks/import", {
      method: "POST",
      body: JSON.stringify({ tasks }),
    }),

  /** Conversation memory + settings, loaded when Bao opens. */
  chatHistory: (limit = 100) =>
    request<BaoChatHistory>(`/bao/chat?limit=${limit}`),

  /** Talk to Bao: it resolves references and may dispatch through the router. */
  chat: (body: {
    text: string;
    scope?: "global" | "project";
    project_key?: string | null;
    agent_id?: string | null;
    thread_id?: string | null;
  }) =>
    request<BaoChatResponse>("/bao/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  settings: () => request<BaoSettings>("/bao/settings"),

  updateSettings: (patch: Partial<BaoSettings>) =>
    request<BaoSettings>("/bao/settings", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
};
