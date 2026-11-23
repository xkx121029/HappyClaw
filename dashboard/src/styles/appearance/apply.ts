/**
 * Applying appearance settings to the live document.
 *
 * Everything here is idempotent and reversible: clearing the settings puts the
 * document back exactly as it was, because every write is either a CSS custom
 * property (removed when absent) or an attribute (`data-appearance-*`).
 */

import { cssVars } from "./derive";
import { checkCustomCss, isDefaultAppearance, type AppearanceSettings } from "./settings";

const STYLE_ID = "octop-appearance-custom-css";
const VAR_PREFIX = "--fn-";

function removeOwnedVars(root: HTMLElement): void {
  for (const name of Array.from(root.style)) {
    if (name.startsWith(VAR_PREFIX)) root.style.removeProperty(name);
  }
}

export function applyAppearanceToDom(settings: AppearanceSettings): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const vars = cssVars(settings);

  removeOwnedVars(root);
  for (const [name, value] of Object.entries(vars)) {
    root.style.setProperty(name, value);
  }

  root.setAttribute("data-appearance-pack", settings.pack);
  root.setAttribute("data-appearance-density", settings.density);

  const existing = document.getElementById(STYLE_ID);
  if (isDefaultAppearance(settings) || !settings.customCss.trim()) {
    existing?.remove();
    return;
  }
  const check = checkCustomCss(settings.customCss);
  if (!check.ok) {
    existing?.remove();
    return;
  }
  const style = existing ?? document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = settings.customCss;
  if (!existing) document.head.appendChild(style);
}

/** Derived token for a preview swatch, exposed for tests. */
export function previewVars(settings: AppearanceSettings): Record<string, string> {
  return cssVars(settings);
}
