import { getAuthToken } from "./http";
import { getWsUrl } from "./http";

export function buildDashboardChatWsUrl(agentId: string): string {
  const token = getAuthToken();
  const encoded = encodeURIComponent(agentId);
  const params = new URLSearchParams();
  if (token) params.set("token", token);
  return getWsUrl(`/agents/${encoded}/chat/ws`, params);
}
