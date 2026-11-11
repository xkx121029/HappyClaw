import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { isWindowOnScreen, type Rect } from "./present";

/**
 * Remember where the single window was last time.
 *
 * Only the Dashboard window is tracked. The guide and the failure page are
 * transient, and restoring their positions would move the main window the user
 * actually cares about.
 */

export interface WindowSize {
  width: number;
  height: number;
}

export type StoredWindowState = Partial<Rect> & { maximized?: boolean };

const DEFAULTS: StoredWindowState = { maximized: false };

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function positive(value: unknown): value is number {
  return finite(value) && value > 0;
}

export function readWindowState(filePath: string): StoredWindowState | null {
  if (!existsSync(filePath)) return null;
  try {
    const raw = JSON.parse(readFileSync(filePath, "utf8")) as Record<string, unknown>;
    const out: StoredWindowState = { maximized: raw.maximized === true };
    for (const key of ["x", "y"] as const) {
      if (finite(raw[key])) out[key] = raw[key] as number;
    }
    for (const key of ["width", "height"] as const) {
      if (positive(raw[key])) out[key] = raw[key] as number;
    }
    return out;
  } catch {
    // A corrupt preference file is not worth a dialog: fall back to defaults.
    return DEFAULTS;
  }
}

export function writeWindowState(
  filePath: string,
  state: Rect & { maximized: boolean },
): void {
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(
    filePath,
    JSON.stringify(
      {
        x: Math.round(state.x),
        y: Math.round(state.y),
        width: Math.round(state.width),
        height: Math.round(state.height),
        maximized: state.maximized,
      },
      null,
      2,
    ),
    "utf8",
  );
}

/**
 * Bounds that are safe to apply, or `null` when Electron should use its own
 * default placement. A stored position from a display that is no longer
 * attached must not put the window off screen.
 */
export function usableWindowBounds(
  state: StoredWindowState,
  workAreas: readonly Rect[],
  minSize: WindowSize,
): Rect | null {
  if (!finite(state.x) || !finite(state.y)) return null;
  const width = Math.max(minSize.width, Math.round(state.width ?? minSize.width));
  const height = Math.max(minSize.height, Math.round(state.height ?? minSize.height));
  const bounds = { x: Math.round(state.x), y: Math.round(state.y), width, height };
  return isWindowOnScreen(bounds, workAreas) ? bounds : null;
}
