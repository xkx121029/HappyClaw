import { getAuthToken } from "../request";
import { getWsUrl } from "../config";

export function buildDashboardNotifyWsUrl(): string {
  const token = getAuthToken();
  const params = new URLSearchParams();
  if (token) params.set("token", token);
  return getWsUrl("/notifications/ws", params);
}
