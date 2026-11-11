import { bridgeAgentHeaders, request } from "../request";
import type { ResolvedModel, TestSearchResponse } from "../types";

/**
 * Provider/model helpers that are actually served by the local backend.
 *
 * 设置页走 ``/admin/providers``；旧的 ``/models/*`` 系列接口在单人本机
 * 后端上返回 404，已确认是死代码并从本模块移除，避免误调用。
 */
export const providerApi = {
  listResolvedModels: (agentId?: string | null) =>
    request<ResolvedModel[]>("/providers/resolved", {
      headers: bridgeAgentHeaders(agentId),
    }),

  getActiveModel: (agentId?: string | null) =>
    request<{ provider_name: string; model: string }>(
      "/providers/active-model",
      { headers: bridgeAgentHeaders(agentId) },
    ),

  /* ---- Test search connectivity ---- */

  testSearch: (providerId: string, envVars: Record<string, string>) =>
    request<TestSearchResponse>(
      `/search/${encodeURIComponent(providerId)}/test`,
      {
        method: "POST",
        body: JSON.stringify({ env_vars: envVars }),
      },
    ),
};
