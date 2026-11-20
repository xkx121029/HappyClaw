import { request, requestUpload } from "../request";

export interface PluginConfigField {
  name: string;
  label?: string;
  type?: string;
  required?: boolean;
  placeholder?: string;
  help?: string;
}

export interface InstalledPlugin {
  id: string;
  version?: string;
  name?: string;
  kind?: string;
  description?: string;
  /** Emoji, absolute image URL, or plugin-relative path resolved to ``/api/plugins/.../ui/...``. */
  icon?: string | null;
  /** Catalog group slug from plugin.yaml (e.g. lifestyle, games). */
  group?: string | null;
  requires?: string[];
  path?: string;
  loaded?: boolean;
  /** Global enable switch from config.json (default true). */
  enabled?: boolean;
  visibility?: "all" | "groups";
  group_ids?: string[];
  error?: string;
  ui?: {
    entry: string;
    manifest: string;
    surfaces?: PluginUiSurfaceDeclaration[];
  } | null;
  tools?: {
    name: string;
    description?: string;
    config_fields?: PluginConfigField[];
  }[];
}

export interface PluginUiSurfaceDeclaration {
  id: string;
  slot: string;
  title: string;
  supported: boolean;
  reason_code: string | null;
}

export interface PluginUiCapabilities {
  api_version: number;
  trust: {
    model: string;
    sandboxed: boolean;
    warning: string;
  };
  slots: { id: string; title: string }[];
  data: { domain: string; description: string; refresh_seconds: number | null }[];
  events: { name: string; description: string }[];
  data_domains: string[];
  event_names: string[];
}

export interface AgentPluginTool {
  plugin_id: string;
  name: string;
  description?: string;
  config_fields: PluginConfigField[];
  enabled: boolean;
  config: Record<string, unknown>;
}

export type AgentPluginsConfig = Record<
  string,
  {
    enabled?: boolean;
    tools?: Record<
      string,
      {
        enabled?: boolean;
        config?: Record<string, unknown>;
      }
    >;
  }
>;

export interface AgentPlugin {
  id: string;
  version?: string | null;
  name?: string | null;
  kind?: string | null;
  description?: string | null;
  icon?: string | null;
  group?: string | null;
  loaded: boolean;
  global_enabled: boolean;
  agent_enabled: boolean;
  /** Effective state: global and Agent switches must both be enabled. */
  enabled: boolean;
  tools: InstalledPlugin["tools"];
}

export interface MarketPlugin {
  id: string;
  version?: string;
  name?: string;
  kind?: string;
  description?: string;
  icon?: string | null;
  group?: string | null;
  requires?: string[];
  installed?: boolean;
  installed_version?: string | null;
  update_available?: boolean;
  error?: string;
  /** ``bundled`` ships in-package; ``portal`` downloads an archive. */
  source?: "bundled" | "portal";
  install_kind?: "bundled" | "archive";
  ui?: InstalledPlugin["ui"];
}

export interface DshMarketError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface DshMarketSource {
  url: string;
  /** One of the verified addresses shipped with the app. */
  builtin?: boolean;
  /** ``stale``: serving cache; ``slow``: timed out, warming cache in background. */
  status: "ok" | "stale" | "slow" | "error" | "unknown";
  error?: DshMarketError | null;
  entry_count: number;
  diagnostics: string;
  fetched_at: string | null;
  stale?: boolean;
  budget_seconds?: number | null;
  elapsed_ms?: number | null;
}

export interface DshProbeReport {
  attempted: boolean;
  ok: boolean;
  code: string | null;
  message: string;
  missing?: string[];
  duration_ms?: number;
}

export interface DshRuntimeStatus {
  status: "missing" | "visible" | "not_visible" | "not_loaded" | "broken";
  visible_to_agents: boolean;
  executable: boolean;
  error_code: string | null;
  reason: string;
  notes: string[];
  probe?: DshProbeReport;
  /** DSH has no HappyClaw UI surface; the reason is explicit, not a failure. */
  surface_supported?: boolean;
  surface_reason_code?: string | null;
  surface_reason?: string;
}

export interface DshMarketEntry {
  plugin_id: string;
  package_name?: string | null;
  name: string;
  description?: string | null;
  icon?: string | null;
  homepage?: string | null;
  tags: string[];
  source_url?: string | null;
  versions: string[];
  recommended_version?: string | null;
  installed: boolean;
  installed_version?: string | null;
  update_available: boolean;
  runtime: DshRuntimeStatus;
}

export interface DshMarketView {
  market_root: string;
  sources: DshMarketSource[];
  /** Only the requested page; ``total`` describes the whole query. */
  entries: DshMarketEntry[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  query: string;
  fetched_at: string;
  cached: boolean;
}

export interface DshStageState {
  name: string;
  env: string;
  configured: boolean;
  effective: boolean;
  gated_by_master: boolean;
}

export interface DshSourceHealth {
  url: string;
  builtin: boolean;
  status: "ok" | "stale" | "slow" | "error" | "unknown";
  entry_count: number;
  error: DshMarketError | null;
  diagnostics: string;
  checked_at: string | null;
  stale?: boolean;
  budget_seconds?: number | null;
  elapsed_ms?: number | null;
}

export interface DshInstalledRuntime {
  plugin_id: string;
  version: string | null;
  install_dir: string | null;
  status: string;
  visible_to_agents: boolean;
  executable: boolean;
  error_code: string | null;
  reason: string;
  notes: string[];
  probe?: DshProbeReport | null;
  ledger_error: string | null;
  surface_supported?: boolean;
  surface_reason_code?: string | null;
  surface_reason?: string;
}

export interface DshFailureRecord {
  at: string;
  kind: "load" | "execute";
  plugin_id: string;
  code: string;
  reason: string;
  detail: string;
}

export interface DshStatusView {
  schema_version: number;
  generated_at: string;
  runtime: {
    enabled: boolean;
    ready: boolean;
    reason_code: string | null;
    reason: string;
    node: { required: boolean; available: boolean | null; version: string | null };
  };
  stages: DshStageState[];
  sources: {
    checked_at: string | null;
    probed: boolean;
    items: DshSourceHealth[];
  };
  installed: DshInstalledRuntime[];
  installed_error: string | null;
  tools: { stage_enabled: boolean; report: Record<string, unknown> | null; error: string | null };
  llm: {
    stage_enabled: boolean;
    installation: Record<string, unknown> | null;
    error: string | null;
  };
  last_failure: DshFailureRecord | null;
  recent_failures: DshFailureRecord[];
}

export type DshDependencyCause =
  | "network"
  | "permission"
  | "resolve"
  | "tool"
  | "unknown";

/** Result of installing the bundle's npm dependency closure. */
export interface DshDependencyReport {
  status: "skipped" | "present" | "installed" | "failed";
  manager: string | null;
  missing: string[];
  code: string | null;
  cause: DshDependencyCause | null;
  message: string;
  output_tail: string;
  duration_ms: number;
}

export interface DshInstallResult {
  plugin_id: string;
  version: string;
  previous_version?: string | null;
  source?: string;
  install_dir: string;
  status:
    | "installed"
    | "installed_not_ready"
    | "installed_dependency_failed"
    | "upgraded"
    | "upgraded_not_ready"
    | "upgraded_dependency_failed";
  dependency?: DshDependencyReport | null;
  runtime: DshRuntimeStatus;
}

export type DshInstallPhase =
  | "queued"
  | "download"
  | "dependencies"
  | "probe"
  | "done";

/** Polled while a load runs so the page shows a phase instead of nothing. */
export interface DshInstallProgress {
  plugin_id: string;
  action: "install" | "upgrade";
  phase: DshInstallPhase;
  status: "running" | "ok" | "not_ready" | "failed";
  progress: number;
  message: string;
  detail: string;
  error_code: string | null;
  started_at: string;
  updated_at: string;
  finished_at: string | null;
}

/** A DSH bundle installed from the DSH market; read from its on-disk ledger. */
export interface DshInstalledPlugin {
  plugin_id: string;
  name?: string | null;
  description?: string | null;
  version?: string | null;
  versions: string[];
  installed_at?: string | null;
  install_dir?: string | null;
  entry?: string | null;
  source_url?: string | null;
  runtime: DshRuntimeStatus;
  error?: string | null;
}

export interface DshInstalledView {
  market_root: string;
  plugins: DshInstalledPlugin[];
}

export interface DshUninstallResult {
  plugin_id: string;
  version: string;
  install_dir: string;
  cleaned: boolean;
  remaining_versions: string[];
}

function dshPageQuery(params?: {
  q?: string;
  page?: number;
  pageSize?: number;
}): string {
  const search = new URLSearchParams();
  const query = params?.q?.trim();
  if (query) search.set("q", query);
  if (params?.page && params.page > 1) search.set("page", String(params.page));
  if (params?.pageSize) search.set("page_size", String(params.pageSize));
  const suffix = search.toString();
  return suffix ? `?${suffix}` : "";
}

export const pluginsApi = {  list(): Promise<InstalledPlugin[]> {
    return request<InstalledPlugin[]>("/plugins");
  },

  listMarket(): Promise<MarketPlugin[]> {
    return request<MarketPlugin[]>("/plugins/market");
  },

  uiCapabilities(): Promise<PluginUiCapabilities> {
    return request<PluginUiCapabilities>("/plugins/ui/capabilities");
  },

  installBundled(pluginId: string, force = false): Promise<InstalledPlugin> {
    const qs = force ? "?force=true" : "";
    return request(
      `/plugins/market/bundled/${encodeURIComponent(pluginId)}/install${qs}`,
      { method: "POST" },
    );
  },

  listDshMarket(params?: {
    q?: string;
    page?: number;
    pageSize?: number;
  }): Promise<DshMarketView> {
    return request<DshMarketView>(`/plugins/market/dsh${dshPageQuery(params)}`);
  },

  listDshInstalled(): Promise<DshInstalledView> {
    return request<DshInstalledView>("/plugins/dsh-installed");
  },

  refreshDshMarket(params?: {
    q?: string;
    page?: number;
    pageSize?: number;
  }): Promise<DshMarketView> {
    return request<DshMarketView>(
      `/plugins/market/dsh/refresh${dshPageQuery(params)}`,
      { method: "POST" },
    );
  },

  dshStatus(probe = false): Promise<DshStatusView> {
    const suffix = probe ? "?probe=true" : "";
    return request<DshStatusView>(`/plugins/dsh/status${suffix}`);
  },

  dshInstallProgress(
    pluginId: string,
  ): Promise<{ plugin_id: string; progress: DshInstallProgress | null }> {
    return request(
      `/plugins/dsh/progress?plugin_id=${encodeURIComponent(pluginId)}`,
    );
  },

  addDshSource(url: string): Promise<{ sources: string[] }> {
    return request("/plugins/market/dsh/sources", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
  },

  removeDshSource(url: string): Promise<{ sources: string[] }> {
    return request(
      `/plugins/market/dsh/sources?url=${encodeURIComponent(url)}`,
      { method: "DELETE" },
    );
  },

  installDsh(
    pluginId: string,
    version?: string,
    force = false,
  ): Promise<DshInstallResult> {
    const params = new URLSearchParams({ plugin_id: pluginId });
    if (version) params.set("version", version);
    if (force) params.set("force", "true");
    return request(`/plugins/market/dsh/install?${params.toString()}`, {
      method: "POST",
    });
  },

  upgradeDsh(
    pluginId: string,
    version?: string,
  ): Promise<DshInstallResult> {
    const params = new URLSearchParams({ plugin_id: pluginId });
    if (version) params.set("version", version);
    return request(`/plugins/market/dsh/upgrade?${params.toString()}`, {
      method: "POST",
    });
  },

  uninstallDsh(
    pluginId: string,
    version?: string,
  ): Promise<DshUninstallResult> {
    const params = new URLSearchParams({ plugin_id: pluginId });
    if (version) params.set("version", version);
    return request(`/plugins/market/dsh/plugin?${params.toString()}`, {
      method: "DELETE",
    });
  },

  installFromMarket(
    pluginId: string,
    version?: string,
  ): Promise<{ id: string; version: string; name: string; kind: string }> {
    const params = new URLSearchParams();
    if (version) params.set("version", version);
    const qs = params.toString();
    return request(
      `/plugins/market/${encodeURIComponent(pluginId)}/install${
        qs ? `?${qs}` : ""
      }`,
      {
        method: "POST",
      },
    );
  },

  install(
    url: string,
  ): Promise<{ id: string; version: string; name: string; kind: string }> {
    return request("/plugins/install", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
  },

  upload(
    file: File,
    force: boolean,
  ): Promise<{ id: string; version: string; name: string; kind: string }> {
    const formData = new FormData();
    formData.append("file", file);
    if (force) formData.append("force", "true");
    return requestUpload("/plugins/upload", formData);
  },

  uninstall(pluginId: string): Promise<{ status: string; id: string }> {
    return request(`/plugins/${encodeURIComponent(pluginId)}`, {
      method: "DELETE",
    });
  },

  setEnabled(pluginId: string, enabled: boolean): Promise<InstalledPlugin> {
    return request(`/plugins/${encodeURIComponent(pluginId)}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
  },

  setVisibility(
    pluginId: string,
    body: { visibility: "all" | "groups"; group_ids?: string[] },
  ): Promise<InstalledPlugin> {
    return request(`/plugins/${encodeURIComponent(pluginId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  reload(): Promise<{
    status: string;
    loaded: { id: string; version: string; kind: string }[];
  }> {
    return request("/plugins/reload", { method: "POST" });
  },

  listAgentTools(agentId: string): Promise<{ tools: AgentPluginTool[] }> {
    return request(`/plugins/agents/${encodeURIComponent(agentId)}/tools`);
  },

  patchAgentTools(
    agentId: string,
    plugins: AgentPluginsConfig,
  ): Promise<{ status: string }> {
    return request(`/plugins/agents/${encodeURIComponent(agentId)}/tools`, {
      method: "PATCH",
      body: JSON.stringify({ plugins }),
    });
  },

  listAgentPlugins(agentId: string): Promise<{ plugins: AgentPlugin[] }> {
    return request(`/plugins/agents/${encodeURIComponent(agentId)}`);
  },

  patchAgentPlugins(
    agentId: string,
    plugins: Record<string, { enabled: boolean }>,
  ): Promise<{ plugins: AgentPlugin[] }> {
    return request(`/plugins/agents/${encodeURIComponent(agentId)}`, {
      method: "PATCH",
      body: JSON.stringify({ plugins }),
    });
  },
};
