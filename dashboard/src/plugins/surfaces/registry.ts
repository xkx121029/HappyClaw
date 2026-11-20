import type { OctopPluginUIHost } from "../toolRenderers/types";
import {
  isSurfaceSlot,
  type RegisteredSurface,
  type SurfaceRegistration,
  type SurfaceSlot,
} from "./types";

const byPlugin = new Map<string, Map<string, RegisteredSurface>>();
const listeners = new Set<() => void>();
let version = 0;

function bump(): void {
  version += 1;
  for (const fn of listeners) {
    try {
      fn();
    } catch {
      /* a broken subscriber must not block other plugins */
    }
  }
}

export function subscribeSurfaces(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Stable snapshot for ``useSyncExternalStore``. */
export function getSurfaceVersion(): number {
  return version;
}

export function registerPluginSurface(
  pluginId: string,
  reg: SurfaceRegistration,
  host: OctopPluginUIHost,
): () => void {
  if (!pluginId || !reg?.id || typeof reg.component !== "function") {
    throw new Error("SURFACE_REGISTER_FAILED");
  }
  if (!isSurfaceSlot(reg.slot)) {
    throw new Error("SURFACE_SLOT_UNKNOWN");
  }
  let entries = byPlugin.get(pluginId);
  if (!entries) {
    entries = new Map();
    byPlugin.set(pluginId, entries);
  }
  const registered: RegisteredSurface = {
    ...reg,
    pluginId,
    title: reg.title?.trim() || reg.id,
    order: Number.isFinite(reg.order) ? Number(reg.order) : 100,
    host,
  };
  entries.set(reg.id, registered);
  bump();

  let disposed = false;
  return () => {
    if (disposed) return;
    disposed = true;
    const current = byPlugin.get(pluginId);
    if (!current) return;
    current.delete(reg.id);
    if (current.size === 0) byPlugin.delete(pluginId);
    bump();
  };
}

export function unregisterPluginSurfaces(pluginId: string): void {
  if (!byPlugin.has(pluginId)) return;
  byPlugin.delete(pluginId);
  bump();
}

export function clearPluginSurfaces(): void {
  if (byPlugin.size === 0) return;
  byPlugin.clear();
  bump();
}

export function listPluginSurfaces(slot: SurfaceSlot): RegisteredSurface[] {
  const out: RegisteredSurface[] = [];
  for (const entries of byPlugin.values()) {
    for (const item of entries.values()) {
      if (item.slot === slot) out.push(item);
    }
  }
  out.sort((left, right) => {
    if (left.order !== right.order) return left.order - right.order;
    if (left.pluginId !== right.pluginId) {
      return left.pluginId.localeCompare(right.pluginId);
    }
    return left.id.localeCompare(right.id);
  });
  return out;
}

export function listPluginSurfaceInfo(
  slot: SurfaceSlot,
): Array<{ id: string; title: string; order: number }> {
  return listPluginSurfaces(slot).map((item) => ({
    id: item.id,
    title: item.title,
    order: item.order,
  }));
}

/** Test/diagnostic helper: every plugin that currently owns a surface. */
export function listSurfacePlugins(): string[] {
  return [...byPlugin.keys()];
}
