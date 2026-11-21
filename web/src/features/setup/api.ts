import { api } from "@/lib/api/client";

/**
 * Setup surface of this build.
 *
 * The wizard's *write* endpoints (`/setup/database`, `/setup/begin`,
 * `/setup/initial-admin`, `/setup/finish`) all answer `SINGLE_USER_UNSUPPORTED`:
 * a single-user instance creates its owner and binds SQLite at boot. What is
 * left, and what this page uses, is the read-only/diagnostic half — status,
 * database probe, provider probe — which works in every build.
 */

export interface SetupStatus {
  setup_required: boolean;
  local_account: boolean;
  wizard_password_required: boolean;
  wizard_password_exists: boolean;
  database_driver: string;
  database_bound: boolean;
  single_user: boolean;
}

export interface ProviderPreset {
  id: string;
  name: string;
  protocol?: string;
  base_url?: string | null;
  models?: { id: string; name?: string }[];
}

export interface DatabaseProbeInput {
  driver: "sqlite" | "postgresql";
  sqlite_path?: string;
  host?: string;
  port?: number;
  database?: string;
  user?: string;
  password?: string;
}

export interface ProviderProbeInput {
  name: string;
  type: string;
  api_key: string;
  base_url?: string;
  model_id: string;
}

export interface ProbeResult {
  ok: boolean;
  message: string;
}

function asProbeResult(value: unknown): ProbeResult {
  if (typeof value !== "object" || value === null) {
    return { ok: false, message: "The server returned no detail." };
  }
  const row = value as {
    ok?: unknown;
    message?: unknown;
    detail?: unknown;
    driver?: unknown;
    user_count?: unknown;
  };
  const parts: string[] = [];
  if (typeof row.driver === "string") parts.push(row.driver);
  if (typeof row.user_count === "number") parts.push(`${row.user_count} users`);
  if (typeof row.message === "string") parts.push(row.message);
  if (typeof row.detail === "string") parts.push(row.detail);
  return {
    ok: Boolean(row.ok),
    message: parts.length > 0 ? parts.join(" · ") : row.ok ? "OK" : "Failed",
  };
}

export async function getSetupStatus(): Promise<SetupStatus> {
  const { data } = await api.GET("/api/setup/status");
  const row = (data ?? {}) as Partial<SetupStatus>;
  return {
    setup_required: Boolean(row.setup_required),
    local_account: Boolean(row.local_account),
    wizard_password_required: Boolean(row.wizard_password_required),
    wizard_password_exists: Boolean(row.wizard_password_exists),
    database_driver: row.database_driver ?? "sqlite",
    database_bound: Boolean(row.database_bound),
    single_user: row.single_user !== false,
  };
}

export async function listPresets(): Promise<ProviderPreset[]> {
  const { data } = await api.GET("/api/setup/presets");
  const rows: unknown[] = Array.isArray(data) ? data : [];
  return rows.flatMap((row): ProviderPreset[] => {
    if (typeof row !== "object" || row === null) return [];
    const preset = row as ProviderPreset;
    if (typeof preset.id !== "string" || typeof preset.name !== "string") return [];
    return [preset];
  });
}

export async function probeDatabase(input: DatabaseProbeInput): Promise<ProbeResult> {
  const { data } = await api.POST("/api/setup/test-database", {
    body: { ...input, port: input.port ?? 5432, adopt_existing: false },
  });
  return asProbeResult(data);
}

export async function probeProvider(input: ProviderProbeInput): Promise<ProbeResult> {
  const { data } = await api.POST("/api/setup/test-provider", {
    body: {
      name: input.name || "probe",
      type: input.type,
      api_key: input.api_key,
      base_url: input.base_url,
      model_id: input.model_id,
    },
  });
  return asProbeResult(data);
}
