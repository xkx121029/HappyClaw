import { api } from "@/lib/api/client";
import { isTransportFailure } from "@/lib/api/errors";

export const settingsKeys = {
  server: ["settings", "server"] as const,
};

export interface UploadSettings {
  max_upload_mb: number;
}

export interface HitlSettings {
  enabled: boolean;
}

export interface Preferences {
  locale: string;
  preferred_model: string | null;
}

/** `GET /api/settings/timezone` → `{ timezone: "Asia/Shanghai" }`. */
export async function getTimezone(): Promise<string> {
  const data = await api.GET("/api/settings/timezone");
  const timezone = (data.data as { timezone?: string } | undefined)?.timezone;
  return timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
}

export async function getUploadSettings(): Promise<UploadSettings> {
  const data = await api.GET("/api/settings/upload");
  const body = (data.data ?? {}) as Partial<UploadSettings>;
  return { max_upload_mb: body.max_upload_mb ?? 0 };
}

export async function getHitlSettings(): Promise<HitlSettings> {
  const data = await api.GET("/api/settings/hitl");
  const body = (data.data ?? {}) as Partial<HitlSettings>;
  return { enabled: Boolean(body.enabled) };
}

export async function getPreferences(): Promise<Preferences> {
  const data = await api.GET("/api/preferences");
  const body = (data.data ?? {}) as Partial<Preferences>;
  return {
    locale: body.locale ?? "zh",
    preferred_model: body.preferred_model ?? null,
  };
}

export async function updatePreferences(
  patch: Partial<Pick<Preferences, "locale">>,
): Promise<Preferences> {
  const data = await api.PATCH("/api/preferences", { body: patch });
  const body = (data.data ?? {}) as Partial<Preferences>;
  return {
    locale: body.locale ?? patch.locale ?? "zh",
    preferred_model: body.preferred_model ?? null,
  };
}

/** Best-effort server settings: an unreachable backend yields nulls, not errors. */
export async function tryServerSettings(): Promise<{
  timezone: string | null;
  upload: UploadSettings | null;
  hitl: HitlSettings | null;
  preferences: Preferences | null;
}> {
  const settle = async <T,>(run: () => Promise<T>): Promise<T | null> => {
    try {
      return await run();
    } catch (error) {
      if (isTransportFailure(error)) return null;
      throw error;
    }
  };
  const [timezone, upload, hitl, preferences] = await Promise.all([
    settle(getTimezone),
    settle(getUploadSettings),
    settle(getHitlSettings),
    settle(getPreferences),
  ]);
  return { timezone, upload, hitl, preferences };
}
