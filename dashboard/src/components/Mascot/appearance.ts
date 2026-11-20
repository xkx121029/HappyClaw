import { useSyncExternalStore } from "react";

import type { MascotInk, MascotShape } from "./engine";

/**
 * One appearance record for every surface that draws Bao.
 *
 * The value is the user's saved preferences (see ``BaoContext``), mirrored into
 * a module store so mascots rendered outside the provider — boot screen, crash
 * fallback, setup, auth — still use the same silhouette and colours.
 */
export interface MascotAppearance {
  shape: MascotShape;
  color: MascotInk;
  bodyColor: string | null;
  eyeColor: string | null;
  followTheme: boolean;
}

export const DEFAULT_MASCOT_APPEARANCE: MascotAppearance = {
  shape: "pebble",
  color: "black",
  bodyColor: null,
  eyeColor: null,
  followTheme: false,
};

const STORAGE_KEY = "octop.bao.appearance.v1";

function readStoredAppearance(): MascotAppearance {
  if (typeof window === "undefined") return DEFAULT_MASCOT_APPEARANCE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_MASCOT_APPEARANCE;
    const stored = JSON.parse(raw) as Partial<MascotAppearance>;
    return {
      shape: stored.shape ?? DEFAULT_MASCOT_APPEARANCE.shape,
      color: stored.color ?? DEFAULT_MASCOT_APPEARANCE.color,
      bodyColor: stored.bodyColor ?? null,
      eyeColor: stored.eyeColor ?? null,
      followTheme: stored.followTheme ?? false,
    };
  } catch {
    return DEFAULT_MASCOT_APPEARANCE;
  }
}

let current = readStoredAppearance();
const listeners = new Set<() => void>();

function sameAppearance(a: MascotAppearance, b: MascotAppearance): boolean {
  return (
    a.shape === b.shape &&
    a.color === b.color &&
    a.bodyColor === b.bodyColor &&
    a.eyeColor === b.eyeColor &&
    a.followTheme === b.followTheme
  );
}

export function getMascotAppearance(): MascotAppearance {
  return current;
}

/** Publish the signed-in user's appearance to every mascot on the page. */
export function syncMascotAppearance(next: MascotAppearance): void {
  if (sameAppearance(current, next)) return;
  current = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage denied: the in-memory copy still covers this session.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useMascotAppearance(): MascotAppearance {
  // One snapshot object per published look, so React can bail out of renders
  // when nothing changed.
  return useSyncExternalStore(subscribe, getMascotAppearance, getMascotAppearance);
}

/**
 * Ink for a live-state hint. The orange/red signal only applies while the body
 * keeps the default palette; a custom body or brand-following body keeps its
 * own colour so the status hint never fights the user's choice.
 */
export function mascotStatusInk(
  appearance: MascotAppearance,
  tone: "working" | "error" | null | undefined,
): MascotInk {
  if (tone && !appearance.bodyColor && !appearance.followTheme) {
    return tone === "working" ? "orange" : "red";
  }
  return appearance.color;
}

/** Test helper: drop the published appearance and the cached copy. */
export function resetMascotAppearance(): void {
  current = DEFAULT_MASCOT_APPEARANCE;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
  listeners.forEach((listener) => listener());
}
