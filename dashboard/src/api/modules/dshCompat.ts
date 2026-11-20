import { request } from "../request";

/** Browser-half asset facts resolved by the Python side. */
export interface DshCompatClient {
  entry: string | null;
  exists: boolean;
  shape: string;
  requires: string[];
  unsupported_requires: string[];
  slots: string[];
  mapped_slots: string[];
  unsupported_slots: string[];
  code: string;
  /** ``/api/dsh-compat/ui/<native>/client.js``; needs the auth header. */
  url: string;
}

export interface DshCompatHost {
  state: string;
  code: string;
  error: string;
  missing: string[];
  published: Record<string, unknown>;
  tools: Array<{ name: string; description?: string }>;
  prompts: Array<{ kind?: string; title?: string }>;
  routes: Array<{ method?: string; path?: string }>;
  unsupported: string[];
  entry_shape: string | null;
  ctx: string[];
}

export interface DshCompatPlugin {
  id: string;
  native_id: string;
  package_name: string;
  version: string;
  title: string;
  category: string;
  package_dir: string;
  allowed: boolean;
  host: DshCompatHost;
  client: DshCompatClient;
  ui: { state: string; error: string };
}

export interface DshCompatStatus {
  enabled: boolean;
  allow: string[];
  node: string | null;
  host_slots: string[];
  plugins: DshCompatPlugin[];
}

export interface DshCompatInventoryEntry {
  plugin_id?: string;
  package_name?: string;
  category?: string;
  code?: string;
  can_run?: boolean;
  [key: string]: unknown;
}

export const dshCompatApi = {
  status(): Promise<DshCompatStatus> {
    return request<DshCompatStatus>("/dsh-compat/status");
  },

  refresh(): Promise<DshCompatStatus> {
    return request<DshCompatStatus>("/dsh-compat/refresh", { method: "POST" });
  },

  start(pluginId: string): Promise<DshCompatPlugin> {
    return request(`/dsh-compat/${encodeURIComponent(pluginId)}/start`, {
      method: "POST",
    });
  },

  stop(pluginId: string): Promise<DshCompatPlugin> {
    return request(`/dsh-compat/${encodeURIComponent(pluginId)}/stop`, {
      method: "POST",
    });
  },

  report(body: {
    plugin_id: string;
    state: string;
    error?: string;
  }): Promise<{ ok: boolean }> {
    return request("/dsh-compat/report", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  callTool(
    pluginId: string,
    toolName: string,
    args: Record<string, unknown> = {},
  ): Promise<Record<string, unknown>> {
    return request(
      `/dsh-compat/${encodeURIComponent(pluginId)}/tools/${encodeURIComponent(toolName)}`,
      { method: "POST", body: JSON.stringify({ arguments: args }) },
    );
  },

  slots(): Promise<{ host_slots: string[]; map: Record<string, string> }> {
    return request("/dsh-compat/slots");
  },

  inventory(): Promise<{
    generated_at?: string;
    plugins?: DshCompatInventoryEntry[];
    [key: string]: unknown;
  }> {
    return request("/dsh-compat/inventory");
  },
};
