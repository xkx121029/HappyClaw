import { getApiUrl } from "../../api/config";
import { getAuthToken } from "../../api/request";
import type { InstalledPlugin } from "../../api/modules/plugins";
import { createPluginUiHost } from "./host";
import { unregisterPluginRenderers } from "./registry";
import { unregisterPluginSurfaces } from "../surfaces/registry";
import type { PluginUiModule } from "./types";

const loadedPlugins = new Set<string>();
const blobUrls: string[] = [];
const cleanups = new Map<string, Array<() => void>>();

async function fetchAuthedText(path: string): Promise<string> {
  const url = getApiUrl(path);
  const token = getAuthToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    throw new Error(`plugin UI fetch failed: ${res.status} ${path}`);
  }
  return res.text();
}

/**
 * Dynamically import a plugin ESM via authenticated fetch + blob URL.
 * Plugins must ship a self-contained ``ui/dist/index.js`` (no relative imports).
 */
async function importPluginEsm(
  pluginId: string,
  entryRel: string,
): Promise<PluginUiModule> {
  // plugin.yaml entry is usually ``ui/dist/index.js``; API paths are under ``…/ui/``.
  const normalized = entryRel.replace(/^\/+/, "");
  const underUi = normalized.startsWith("ui/")
    ? normalized.slice(3)
    : normalized;
  const apiPath = `/plugins/${encodeURIComponent(pluginId)}/ui/${underUi}`;
  const source = await fetchAuthedText(apiPath);
  const blob = new Blob([source], { type: "text/javascript" });
  const blobUrl = URL.createObjectURL(blob);
  blobUrls.push(blobUrl);
  return (await import(/* @vite-ignore */ blobUrl)) as PluginUiModule;
}

function runSetup(mod: PluginUiModule, pluginId: string): void {
  const host = createPluginUiHost(pluginId);
  const setup = mod.setup ?? mod.default?.setup;
  if (typeof setup !== "function") return;
  const cleanup = setup(host);
  if (typeof cleanup === "function") {
    const existing = cleanups.get(pluginId) ?? [];
    existing.push(cleanup);
    cleanups.set(pluginId, existing);
  }
}

/** Load UI modules for installed plugins that declare ``ui.entry``. */
export async function loadInstalledPluginUis(
  plugins: InstalledPlugin[],
): Promise<void> {
  for (const plugin of plugins) {
    if (plugin.error || !plugin.ui?.entry) continue;
    if (loadedPlugins.has(plugin.id)) continue;
    try {
      const mod = await importPluginEsm(plugin.id, plugin.ui.entry);
      unregisterPluginRenderers(plugin.id);
      runSetup(mod, plugin.id);
      loadedPlugins.add(plugin.id);
    } catch (err) {
      // A setup that throws halfway may have registered a surface already.
      unregisterPluginSurfaces(plugin.id);
      console.warn(`[plugin-ui] failed to load ${plugin.id}:`, err);
    }
  }
}

/**
 * Force re-fetch and re-register UI modules (after install/uninstall in Admin).
 * Keeps builtin renderers; drops previously loaded third-party UI blobs.
 */
export async function reloadPluginToolUis(
  plugins: InstalledPlugin[],
): Promise<void> {
  resetPluginUiLoader();
  await loadInstalledPluginUis(plugins);
}

/** Drop cached load state (e.g. after uninstall); blob URLs are revoked. */
export function resetPluginUiLoader(): void {
  for (const [id, fns] of cleanups) {
    for (const fn of fns) {
      try {
        fn();
      } catch (err) {
        console.warn(`[plugin-ui] cleanup failed for ${id}:`, err);
      }
    }
  }
  for (const id of loadedPlugins) {
    unregisterPluginRenderers(id);
    unregisterPluginSurfaces(id);
  }
  cleanups.clear();
  loadedPlugins.clear();
  while (blobUrls.length) {
    const url = blobUrls.pop();
    if (url) URL.revokeObjectURL(url);
  }
}

export function isPluginUiLoaded(pluginId: string): boolean {
  return loadedPlugins.has(pluginId);
}
