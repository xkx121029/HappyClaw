import { bridgeAgentHeaders, request } from "../request";

export interface OctopTimezoneSettings {
  timezone: string;
}

export interface OctopUploadSettings {
  max_upload_mb: number;
  max_upload_bytes: number;
}

export interface OctopHitlSettings {
  enabled: boolean;
  tool_guard_require_approval: boolean;
  show_approval_ui: boolean;
}

export interface CaptchaPairView {
  site_key: string;
  has_secret: boolean;
  cam_secret_id?: string;
  has_cam_secret?: boolean;
}

export interface CaptchaSettings {
  active: string;
  available: string[];
  providers: Record<string, CaptchaPairView>;
  source: "settings" | "env";
  v3_min_score: number;
}

export type CaptchaPairBody = {
  site_key?: string;
  secret?: string;
  cam_secret_id?: string;
  cam_secret?: string;
} | null;

export interface CaptchaSettingsPut {
  active?: string;
  providers?: Record<string, CaptchaPairBody>;
}

export interface WebauthnSettings {
  rp_id: string | null;
  origins: string[];
  passwordless_login: boolean;
}

export interface WebauthnSettingsPut {
  rp_id?: string | null;
  origins?: string[];
  passwordless_login?: boolean;
}

export type SearchSourceValue = "happysearch" | "searchfree" | "both";

export interface SearchSourceSettings {
  effective: SearchSourceValue;
  stored: SearchSourceValue | null;
  env: SearchSourceValue | null;
  origin: "env" | "settings" | "default";
  applied: boolean;
}

export interface SearchRuntimeLast {
  query?: string;
  started_at?: number;
  finished_at?: number;
  status?: string;
  source?: string;
  degraded?: boolean;
  elapsed_ms?: number;
  returned?: number;
  fallback?: boolean;
  error?: string | null;
}

export interface SearchEngineLast {
  status?: string;
  count?: number;
  elapsed_ms?: number;
  error?: string | null;
  at?: number;
}

export interface SearchStatus {
  source: Omit<SearchSourceSettings, "applied">;
  tools_visible: string[];
  commercial_providers: string[];
  happysearch: {
    enabled: boolean;
    runtime: {
      runs: number;
      fallbacks: number;
      errors: number;
      in_flight: number;
      last: SearchRuntimeLast | null;
      engines_last: Record<string, SearchEngineLast>;
    };
  };
  searchfree: {
    enabled: boolean;
    runtime: {
      runs: number;
      errors: number;
      in_flight: number;
      last: SearchRuntimeLast | null;
    };
  };
  last: {
    used_source: string;
    query?: string;
    elapsed_ms?: number;
    fallback: boolean;
    fallback_count: number;
    status?: string;
    degraded: boolean;
    at?: number;
  } | null;
}

export const octopSettingsApi = {
  timezone: () => request<OctopTimezoneSettings>("/settings/timezone"),
  upload: () => request<OctopUploadSettings>("/settings/upload"),
  hitl: (agentId?: string | null) =>
    request<OctopHitlSettings>("/settings/hitl", {
      headers: bridgeAgentHeaders(agentId),
    }),
  captcha: () => request<CaptchaSettings>("/settings/captcha"),
  putCaptcha: (body: CaptchaSettingsPut) =>
    request<CaptchaSettings>("/settings/captcha", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  webauthn: () => request<WebauthnSettings>("/settings/webauthn"),
  putWebauthn: (body: WebauthnSettingsPut) =>
    request<WebauthnSettings>("/settings/webauthn", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  searchSource: () => request<SearchSourceSettings>("/settings/search-source"),
  putSearchSource: (body: { source: SearchSourceValue }) =>
    request<SearchSourceSettings>("/settings/search-source", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  searchStatus: () => request<SearchStatus>("/search/status"),
};
