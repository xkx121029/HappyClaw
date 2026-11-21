/**
 * Chat payloads. The backend documents these routes without a `response_model`
 * (they return `dict`), so the generated OpenAPI types are `Record<string,
 * unknown>`. We declare the shapes we actually read here, in one place, and
 * narrow at the boundary in `api.ts`.
 */

export type AgentState = "running" | "stopped" | "starting" | "stopping" | "failed";

export interface Agent {
  agent_id: string;
  name: string;
  description: string | null;
  state: AgentState | string;
  icon_url?: string | null;
  default_model?: string | null;
  unread_count?: number;
}

export interface Thread {
  thread_id: string;
  title: string | null;
  channel_type: string;
  last_active: number;
  created_at: number;
  has_messages?: boolean;
  unread_count?: number;
  model_ref?: string | null;
}

export interface HistoryMessage {
  id?: string;
  role: string;
  content: unknown;
  timestamp?: number;
  status?: string;
  agent_id?: string;
}

export interface ThreadHistory {
  thread_id: string;
  messages: HistoryMessage[];
  has_more?: boolean;
  next_cursor?: string | null;
  turn_active?: boolean;
}

/** True when the response looks like the shape the UI relies on. */
export function isAgent(value: unknown): value is Agent {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Agent).agent_id === "string" &&
    typeof (value as Agent).name === "string"
  );
}

export function isThread(value: unknown): value is Thread {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Thread).thread_id === "string"
  );
}
