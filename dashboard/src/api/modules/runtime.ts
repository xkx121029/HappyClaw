import { request } from "../request";

/** Backend runtime counters exposed by ``GET /api/runtime/activity``. */
export interface RuntimeActivity {
  /** True while any agent turn or terminal session is live. */
  busy: boolean;
  /** Contract read by the desktop quit guard; always has agent_turn/terminal. */
  counts: Record<string, number>;
  active_turns: number;
  dashboard_connections: number;
  threads_with_subscribers: number;
  terminal_sessions: number;
  running_agents: number;
  running_jobs: number;
  /** Unix seconds when the backend last recomputed the payload. */
  updated_at: number;
}

export const runtimeApi = {
  activity: () => request<RuntimeActivity>("/runtime/activity"),
};
