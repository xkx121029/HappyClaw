/**
 * Appearance store: one value, one writer, applied immediately.
 *
 * Kept out of ThemeContext on purpose — that context owns light/dark and the
 * brand palette, and this layer must not disturb it. A module-level store with
 * `useSyncExternalStore` means the settings page, `App.tsx` (which feeds antd)
 * and any future consumer all read the same object, and a change re-renders
 * them together without prop drilling.
 */

import { useSyncExternalStore } from "react";

import { applyAppearanceToDom } from "./apply";
import {
  DEFAULT_APPEARANCE,
  isDefaultAppearance,
  readAppearance,
  writeAppearance,
  type AppearanceSettings,
} from "./settings";

let current: AppearanceSettings = readAppearance();
const listeners = new Set<() => void>();

// Apply the stored settings before the first render: a saved radius or pack must
// be in effect on reload, not only after the user touches a control.
if (typeof document !== 'undefined') applyAppearanceToDom(current);

function emit(): void {
  for (const listener of listeners) listener();
}

export function getAppearance(): AppearanceSettings {
  return current;
}

export function setAppearance(next: AppearanceSettings): void {
  current = next;
  writeAppearance(next);
  applyAppearanceToDom(next);
  emit();
}

export function resetAppearance(): void {
  setAppearance({ ...DEFAULT_APPEARANCE });
}

export function subscribeAppearance(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAppearance(): AppearanceSettings {
  return useSyncExternalStore(subscribeAppearance, getAppearance, getAppearance);
}

export { isDefaultAppearance };

/** Apply the stored settings once, before the first paint. */
export function bootAppearance(): AppearanceSettings {
  applyAppearanceToDom(current);
  return current;
}
