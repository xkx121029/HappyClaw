import { request } from "../request";

export interface PhoneAccessStatus {
  enabled: boolean;
  bind_host: string;
  running_bind_host: string | null;
  port: number;
  token: string;
  urls: string[];
  /** Changes are written to config.json but only apply after a restart. */
  restart_required: boolean;
  /** ``OCTOP_BIND_HOST`` / ``OCTOP_ACCESS_TOKEN`` override the file. */
  managed_by_env: boolean;
  config_path: string;
}

export interface PhoneAccessUpdate {
  enabled?: boolean;
  regenerate_token?: boolean;
}

export const phoneAccessApi = {
  get: () => request<PhoneAccessStatus>("/phone-access"),

  update: (body: PhoneAccessUpdate) =>
    request<PhoneAccessStatus>("/phone-access", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  rotateToken: () =>
    request<PhoneAccessStatus>("/phone-access/token", { method: "POST" }),
};
