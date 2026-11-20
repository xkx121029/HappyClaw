import { request } from "../request";
import type {
  OctopCronRow,
  OctopCronRun,
  OctopCronCreateBody,
  OctopCronPatchBody,
} from "../types";

export interface OctopCronSettings {
  timezone: string;
}

export interface CronTaskExamples {
  zh?: string[];
  en?: string[];
}

export const octopCronApi = {
  settings: () => request<OctopCronSettings>("/cron/settings"),

  list: (agentId: string) => request<OctopCronRow[]>(`/agents/${agentId}/cron`),

  create: (agentId: string, body: OctopCronCreateBody) =>
    request<OctopCronRow>(`/agents/${agentId}/cron`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  get: (agentId: string, cronId: string) =>
    request<OctopCronRow>(`/agents/${agentId}/cron/${cronId}`),

  patch: (agentId: string, cronId: string, body: OctopCronPatchBody) =>
    request<OctopCronRow>(`/agents/${agentId}/cron/${cronId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  delete: (agentId: string, cronId: string) =>
    request<void>(`/agents/${agentId}/cron/${cronId}`, { method: "DELETE" }),

  runs: (agentId: string, cronId: string, limit = 20) =>
    request<OctopCronRun[]>(
      `/agents/${agentId}/cron/${cronId}/runs?limit=${limit}`,
    ),

  runNow: (agentId: string, cronId: string) =>
    request<{ run_id: string }>(`/agents/${agentId}/cron/${cronId}/run-now`, {
      method: "POST",
    }),
};
