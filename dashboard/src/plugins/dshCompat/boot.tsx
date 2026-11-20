/**
 * Boots the DSH compatibility adapter's browser half.
 *
 * The Python side tells us which installed bundles are allowed and have a
 * servable client bundle; we fetch that bundle, mount it on the loader shim,
 * and register one HappyClaw surface per mapped DSH slot. A bundle that throws
 * is reported to ``/dsh-compat/report`` and skipped — it never blocks another
 * plugin or the host page.
 */

import { getApiUrl } from "../../api/config";
import { getAuthToken } from "../../api/request";
import {
  dshCompatApi,
  type DshCompatPlugin,
  type DshCompatStatus,
} from "../../api/modules/dshCompat";
import { createPluginUiHost } from "../toolRenderers/host";
import type { SurfaceSlot } from "../surfaces/types";
import {
  DshSlotSurface,
  mapDshSlot,
  mountDshClient,
  type DshMountResult,
} from "./loaderShim";

/** Client assets that mount as-is; everything else is reported, not retried. */
const MOUNTABLE_CODES = new Set(["OK", "MISSING_API"]);

interface MountedPlugin {
  pluginId: string;
  result: DshMountResult;
  disposers: Array<() => void>;
}

const mounted = new Map<string, MountedPlugin>();
let booting: Promise<void> | null = null;

function clientSourceUrl(plugin: DshCompatPlugin): string {
  return getApiUrl(`/dsh-compat/ui/${encodeURIComponent(plugin.native_id)}/client.js`);
}

async function fetchClientSource(plugin: DshCompatPlugin): Promise<string> {
  const token = getAuthToken();
  const response = await fetch(clientSourceUrl(plugin), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    throw new Error(`CLIENT_FETCH_${response.status}`);
  }
  return response.text();
}

async function report(pluginId: string, state: string, error = ""): Promise<void> {
  try {
    await dshCompatApi.report({ plugin_id: pluginId, state, error: error.slice(0, 500) });
  } catch {
    /* reporting is diagnostic; losing it must not break mounting */
  }
}

async function mountPlugin(plugin: DshCompatPlugin): Promise<void> {
  if (mounted.has(plugin.id)) return;
  const host = createPluginUiHost(plugin.id);
  let result: DshMountResult;
  try {
    const source = await fetchClientSource(plugin);
    result = await mountDshClient({
      pluginId: plugin.id,
      host,
      source,
      sourceUrl: clientSourceUrl(plugin),
    });
  } catch (error) {
    await report(plugin.id, "failed", `${typeName(error)}: ${String(error)}`);
    return;
  }

  const slots = new Set<SurfaceSlot>();
  for (const entry of result.entries) {
    const target = mapDshSlot(entry.dshSlot);
    if (target) slots.add(target.slot);
  }

  const disposers: Array<() => void> = [];
  try {
    for (const slot of slots) {
      const dispose = host.surfaces.register({
        id: `dsh:${slot}`,
        slot,
        title: plugin.title || plugin.package_name || plugin.id,
        order: 100,
        component: (props) => (
          <DshSlotSurface
            result={result}
            slot={slot}
            host={props.host}
            context={props.context}
          />
        ),
      });
      disposers.push(dispose);
    }
  } catch (error) {
    result.dispose();
    await report(plugin.id, "failed", `SURFACE_REGISTER: ${String(error)}`);
    return;
  }

  mounted.set(plugin.id, { pluginId: plugin.id, result, disposers });
  const unsupported = [...result.unsupportedSlots, ...result.unsupportedMembers];
  await report(
    plugin.id,
    slots.size > 0 ? "mounted" : "no-surface",
    unsupported.join(", "),
  );
}

function typeName(error: unknown): string {
  return error instanceof Error ? error.name : typeof error;
}

async function bootFrom(status: DshCompatStatus): Promise<void> {
  if (!status.enabled) return;
  const candidates = status.plugins.filter(
    (plugin) =>
      plugin.allowed &&
      plugin.client.exists &&
      MOUNTABLE_CODES.has(plugin.client.code),
  );
  for (const plugin of candidates) {
    try {
      await mountPlugin(plugin);
    } catch (error) {
      // Belt and braces: mountPlugin already reports, but a bug in the shim
      // itself must not stop the remaining plugins from loading.
      await report(plugin.id, "failed", `BOOT: ${String(error)}`);
    }
  }
}

/** Cheap wait for the login token; a login page has nothing to mount. */
async function waitForToken(timeoutMs = 30_000): Promise<boolean> {
  if (getAuthToken()) return true;
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    await new Promise((resolve) => window.setTimeout(resolve, 1_000));
    if (getAuthToken()) return true;
  }
  return false;
}

/** Public entry: idempotent, never throws. */
export function startDshCompat(): Promise<void> {
  if (booting) return booting;
  booting = (async () => {
    try {
      if (!(await waitForToken())) return;
      const status = await dshCompatApi.status();
      await bootFrom(status);
    } catch (error) {
      console.warn("[dsh-compat] boot skipped:", error);
    }
  })();
  return booting;
}

/** Test/diagnostic helper: which plugins currently render surfaces. */
export function mountedDshPlugins(): string[] {
  return [...mounted.keys()];
}
