import { api } from "@/lib/api/client";

export interface UsageBucket {
  key: string;
  label: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
  model_calls: number;
  turns: number;
}

export interface UsageReport {
  window: string;
  range_start: number;
  range_end: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  model_calls: number;
  turns: number;
  cache_hit_percent: number;
  buckets: UsageBucket[];
}

export type UsageWindow = "last_7d" | "last_30d" | "all";

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function toBucket(value: unknown, index: number): UsageBucket | null {
  if (typeof value !== "object" || value === null) return null;
  const row = value as Record<string, unknown>;
  return {
    key: typeof row.key === "string" ? row.key : String(index),
    label: typeof row.label === "string" ? row.label : String(row.key ?? index),
    input_tokens: num(row.input_tokens),
    output_tokens: num(row.output_tokens),
    cache_read_tokens: num(row.cache_read_tokens),
    total_tokens: num(row.total_tokens),
    model_calls: num(row.model_calls),
    turns: num(row.turns),
  };
}

/** `GET /api/usage/summary` — dict-typed, so fields are narrowed here. */
export async function getUsageReport(window: UsageWindow): Promise<UsageReport> {
  const { data } = await api.GET("/api/usage/summary", {
    params: { query: { window, granularity: "by_day" } },
  });
  const body = (data ?? {}) as Record<string, unknown>;
  const buckets = Array.isArray(body.buckets)
    ? body.buckets
        .map((row, index) => toBucket(row, index))
        .filter((row): row is UsageBucket => row !== null)
    : [];
  return {
    window: typeof body.window === "string" ? body.window : window,
    range_start: num(body.range_start),
    range_end: num(body.range_end),
    input_tokens: num(body.input_tokens),
    output_tokens: num(body.output_tokens),
    total_tokens: num(body.total_tokens),
    model_calls: num(body.model_calls),
    turns: num(body.turns),
    cache_hit_percent: num(body.cache_hit_percent),
    buckets,
  };
}
