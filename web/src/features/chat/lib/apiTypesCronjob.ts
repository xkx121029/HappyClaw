export interface CronJobSchedule {
  type: "cron";
  cron: string;
  timezone?: string;
}

export interface CronJobTarget {
  user_id: string;
  session_id: string;
}

export interface CronJobDispatch {
  type: "channel";
  channel?: string | string[];
  target: CronJobTarget;
  mode?: "stream" | "final";
  meta?: Record<string, unknown>;
}

export interface CronJobRuntime {
  max_concurrency?: number;
  timeout_seconds?: number;
  misfire_grace_seconds?: number;
}

export interface CronJobRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  [key: string]: unknown;
}

export interface CronJobSpecInput {
  id: string;
  name: string;
  enabled?: boolean;
  schedule: CronJobSchedule;
  task_type?: "text" | "agent";
  text?: string;
  request?: CronJobRequest;
  dispatch: CronJobDispatch;
  model?: string | null;
  runtime?: CronJobRuntime;
  meta?: Record<string, unknown>;
}

export type CronJobSpecOutput = CronJobSpecInput;

export interface CronJobView extends CronJobSpecOutput {
  // Extended view with runtime state
  state?: unknown;
  next_run_time?: number;
  last_run_time?: number;
}

export type CronJobSpecInputLegacy = Record<string, unknown>;
export type CronJobSpecOutputLegacy = Record<string, unknown>;
export type CronJobViewLegacy = Record<string, unknown>;

// ---------------------------------------------------------------------------
// Octop-native flat cron row — returned by /api/agents/:id/cron endpoints
// ---------------------------------------------------------------------------

/**
 * Wire-shape returned by octop's per-agent cron endpoints.
 * Matches the Python ``_row_to_dict`` serializer in ``api/routers/cron.py``.
 */
export interface OctopCronRow {
  id: string;
  name: string;
  agent_id: string;
  trigger: string;
  prompt: string;
  session_key: string;
  fresh_thread: boolean;
  enabled: boolean;
  task_type: "text" | "agent";
  model: string | null;
  mcp_servers?: string[];
  last_run_at: number | null;
  last_status: string | null;
  last_error: string | null;
  /** IANA zone the trigger is interpreted in; empty means the server default. */
  timezone?: string;
  /** Planned next fire time (unix seconds); null for mail/one-shot-done. */
  next_run_at?: number | null;
  max_retries?: number;
  retry_backoff_seconds?: number;
  catch_up_misses?: number;
  consecutive_failures?: number;
}

/** One row from GET /api/agents/:id/cron/:cron_id/runs */
export interface OctopCronRun {
  run_id: string;
  cron_id: string;
  trigger_kind: "schedule" | "manual" | "mail" | "catchup";
  scheduled_for: number | null;
  status: "running" | "ok" | "error" | "missed" | "skipped";
  attempt: number;
  started_at: number;
  finished_at: number | null;
  duration_ms: number | null;
  error: string | null;
  note: string | null;
}

/** Body sent to POST /api/agents/:id/cron */
export interface OctopCronCreateBody {
  name?: string | null;
  trigger: string;
  prompt: string;
  session_key?: string | null;
  fresh_thread?: boolean;
  enabled?: boolean;
  model?: string | null;
  task_type?: "text" | "agent";
  mcp_servers?: string[];
  timezone?: string | null;
  max_retries?: number;
  retry_backoff_seconds?: number;
  catch_up_misses?: number;
}

/** Body sent to PATCH /api/agents/:id/cron/:cron_id */
export interface OctopCronPatchBody {
  name?: string | null;
  trigger?: string;
  prompt?: string;
  session_key?: string | null;
  fresh_thread?: boolean;
  enabled?: boolean;
  model?: string | null;
  task_type?: "text" | "agent";
  mcp_servers?: string[];
  timezone?: string | null;
  max_retries?: number;
  retry_backoff_seconds?: number;
  catch_up_misses?: number;
}
