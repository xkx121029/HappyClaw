/**
 * Appearance settings — the deep-customisation model.
 *
 * Every dimension has a "leave it alone" value ("default" / "standard" /
 * "system"). The defaults are all of them, so a user who never opens the
 * appearance page keeps exactly the look the app has always had: the applier
 * returns no overrides at all in that case, which makes a visual change
 * structurally impossible rather than merely unlikely.
 */

export type RadiusChoice = "default" | "0" | "4" | "8" | "12" | "16" | "custom";
export type Density = "standard" | "compact" | "comfortable";
export type FontSizeChoice = "xs" | "small" | "standard" | "large" | "xl";
export type FontFamilyChoice = "system" | "serif" | "mono";
export type ThemePack = "default" | "instrument" | "warmPaper" | "highContrast";

export interface AppearanceSettings {
  pack: ThemePack;
  radius: RadiusChoice;
  /** Used only when `radius === "custom"`. */
  customRadius: number | null;
  density: Density;
  fontSize: FontSizeChoice;
  fontFamily: FontFamilyChoice;
  /** Raw CSS appended after the built-in sheets. Validated on write. */
  customCss: string;
}

export const APPEARANCE_STORAGE_KEY = "octop:appearance";
export const APPEARANCE_SCHEMA_VERSION = 1;
/** Exported files carry this marker so a random JSON cannot be imported. */
export const APPEARANCE_EXPORT_MARKER = "octop-appearance";

export const RADIUS_CHOICES: RadiusChoice[] = ["0", "4", "8", "12", "16", "custom"];
export const DENSITIES: Density[] = ["compact", "standard", "comfortable"];
export const FONT_SIZE_CHOICES: FontSizeChoice[] = ["xs", "small", "standard", "large", "xl"];
export const FONT_FAMILIES: FontFamilyChoice[] = ["system", "serif", "mono"];
export const THEME_PACKS: ThemePack[] = ["default", "instrument", "warmPaper", "highContrast"];

export const DEFAULT_APPEARANCE: AppearanceSettings = {
  pack: "default",
  radius: "default",
  customRadius: null,
  density: "standard",
  fontSize: "standard",
  fontFamily: "system",
  customCss: "",
};

/** True when nothing is overridden — the app must look untouched. */
export function isDefaultAppearance(settings: AppearanceSettings): boolean {
  return (
    settings.pack === "default" &&
    settings.radius === "default" &&
    settings.density === "standard" &&
    settings.fontSize === "standard" &&
    settings.fontFamily === "system" &&
    settings.customCss.trim() === ""
  );
}

export interface CustomCssCheck {
  ok: boolean;
  /** Localised message key suffix for the UI; undefined when ok. */
  reason?: "import" | "remoteUrl" | "script" | "unbalanced";
}

/**
 * The custom-CSS box must not become an injection surface: no `@import`, no
 * remote `url(...)`, no `<script`, and braces must balance so a half-typed rule
 * cannot swallow the rest of the sheet.
 */
export function checkCustomCss(css: string): CustomCssCheck {
  const lower = css.toLowerCase();
  if (/@import\b/.test(lower)) return { ok: false, reason: "import" };
  if (/url\(\s*['"]?\s*(https?:)?\/\//.test(lower)) return { ok: false, reason: "remoteUrl" };
  if (/<\s*\/?\s*script/.test(lower)) return { ok: false, reason: "script" };
  const opens = (css.match(/\{/g) ?? []).length;
  const closes = (css.match(/\}/g) ?? []).length;
  if (opens !== closes) return { ok: false, reason: "unbalanced" };
  return { ok: true };
}

function pick<T>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/** Accepts anything (stored JSON, imported file) and yields valid settings. */
export function parseAppearance(raw: unknown): AppearanceSettings {
  if (!raw || typeof raw !== "object") return { ...DEFAULT_APPEARANCE };
  const row = raw as Record<string, unknown>;
  const customRadius =
    typeof row.customRadius === "number" && Number.isFinite(row.customRadius)
      ? Math.min(64, Math.max(0, Math.round(row.customRadius)))
      : null;
  const customCss = typeof row.customCss === "string" ? row.customCss.slice(0, 20000) : "";
  const radius = pick(row.radius, ["default", ...RADIUS_CHOICES] as const, "default");
  return {
    pack: pick(row.pack, THEME_PACKS, "default"),
    radius,
    customRadius: radius === "custom" && customRadius === null ? 8 : customRadius,
    density: pick(row.density, DENSITIES, "standard"),
    fontSize: pick(row.fontSize, FONT_SIZE_CHOICES, "standard"),
    fontFamily: pick(row.fontFamily, FONT_FAMILIES, "system"),
    customCss: checkCustomCss(customCss).ok ? customCss : "",
  };
}

export function readAppearance(storage: Storage | undefined = globalThis.localStorage): AppearanceSettings {
  if (!storage) return { ...DEFAULT_APPEARANCE };
  try {
    const raw = storage.getItem(APPEARANCE_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_APPEARANCE };
    return parseAppearance(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_APPEARANCE };
  }
}

export function writeAppearance(
  settings: AppearanceSettings,
  storage: Storage | undefined = globalThis.localStorage,
): void {
  if (!storage) return;
  try {
    storage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(settings));
  } catch {
    /* a full quota must not break the UI */
  }
}

/** JSON the user can keep or share. */
export function exportAppearance(settings: AppearanceSettings): string {
  return JSON.stringify(
    { marker: APPEARANCE_EXPORT_MARKER, version: APPEARANCE_SCHEMA_VERSION, ...settings },
    null,
    2,
  );
}

export interface ImportResult {
  ok: boolean;
  settings?: AppearanceSettings;
  error?: "parse" | "marker" | "css";
}

export function importAppearance(text: string): ImportResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, error: "parse" };
  }
  if (!parsed || typeof parsed !== "object") return { ok: false, error: "parse" };
  if ((parsed as { marker?: unknown }).marker !== APPEARANCE_EXPORT_MARKER) {
    return { ok: false, error: "marker" };
  }
  const settings = parseAppearance(parsed);
  if (settings.customCss && !checkCustomCss(settings.customCss).ok) {
    return { ok: false, error: "css" };
  }
  return { ok: true, settings };
}
