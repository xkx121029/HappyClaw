/**
 * Turns appearance settings into concrete tokens.
 *
 * Two outputs, from one source:
 *   - `antdOverrides()` → token/component overrides merged into the antd theme,
 *     so every antd surface (button, input, card, modal, drawer, table, select,
 *     menu…) follows the choice at once;
 *   - `cssVars()` → `--fn-*` custom properties for the LESS stylesheets that do
 *     not go through antd (message bubbles, code blocks, layout chrome).
 *
 * Derivation is proportional to the existing scales rather than invented
 * numbers: density scales control heights, font size scales the type ramp.
 */

import { CONTROL_HEIGHT, FONT_SIZE, RADIUS } from "../tokens/scales";
import type { ThemeConfig } from "antd";

import {
  isDefaultAppearance,
  type AppearanceSettings,
  type Density,
  type FontFamilyChoice,
  type FontSizeChoice,
} from "./settings";

export const FONT_SIZE_MULTIPLIER: Record<FontSizeChoice, number> = {
  xs: 0.88,
  small: 0.94,
  standard: 1,
  large: 1.08,
  xl: 1.16,
};

export const DENSITY_SCALE: Record<Density, number> = {
  compact: 0.85,
  standard: 1,
  comfortable: 1.15,
};

export const FONT_STACKS: Record<FontFamilyChoice, string> = {
  system:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Noto Sans SC", "Microsoft YaHei", sans-serif',
  serif:
    '"Source Han Serif SC", "Noto Serif SC", "Songti SC", Georgia, "Times New Roman", serif',
  mono:
    'ui-monospace, "SFMono-Regular", "Cascadia Mono", Consolas, "Noto Sans SC", monospace',
};

export function radiusPx(settings: AppearanceSettings): number | null {
  if (settings.radius === "default") return null;
  if (settings.radius === "custom") {
    const value = settings.customRadius;
    return typeof value === "number" ? Math.min(64, Math.max(0, Math.round(value))) : RADIUS.md;
  }
  return Number(settings.radius);
}

export function scaledFontSize(step: number, choice: FontSizeChoice): number {
  return Math.round(step * FONT_SIZE_MULTIPLIER[choice]);
}

export function scaledControlHeight(value: number, density: Density): number {
  return Math.round(value * DENSITY_SCALE[density]);
}

/** antd token + component overrides. Empty object when nothing is customised. */
export function antdOverrides(settings: AppearanceSettings): ThemeConfig {
  if (isDefaultAppearance(settings)) return {};
  const token: NonNullable<ThemeConfig["token"]> = {};
  const radius = radiusPx(settings);
  if (radius !== null) {
    token.borderRadius = radius;
    token.borderRadiusXS = Math.max(0, radius - 4);
    token.borderRadiusSM = Math.max(0, radius - 2);
    token.borderRadiusLG = radius + 2;
  }
  if (settings.density !== "standard") {
    token.controlHeight = scaledControlHeight(CONTROL_HEIGHT.md, settings.density);
    token.controlHeightSM = scaledControlHeight(CONTROL_HEIGHT.sm, settings.density);
    token.controlHeightLG = scaledControlHeight(CONTROL_HEIGHT.lg, settings.density);
  }
  if (settings.fontSize !== "standard") {
    token.fontSize = scaledFontSize(FONT_SIZE.sm, settings.fontSize);
    token.fontSizeSM = scaledFontSize(FONT_SIZE["2xs"], settings.fontSize);
    token.fontSizeLG = scaledFontSize(FONT_SIZE.lg, settings.fontSize);
    token.fontSizeXL = scaledFontSize(FONT_SIZE.xl, settings.fontSize);
    token.fontSizeHeading1 = scaledFontSize(FONT_SIZE["2xl"], settings.fontSize);
    token.fontSizeHeading2 = scaledFontSize(FONT_SIZE.xl, settings.fontSize);
    token.fontSizeHeading3 = scaledFontSize(FONT_SIZE.lg, settings.fontSize);
  }
  if (settings.fontFamily !== "system") {
    token.fontFamily = FONT_STACKS[settings.fontFamily];
  }
  return {
    token,
    components: settings.density === "standard" ? undefined : {
      Table: {
        cellPaddingBlock: scaledControlHeight(8, settings.density),
        cellPaddingInline: scaledControlHeight(16, settings.density),
      },
      Menu: { itemHeight: scaledControlHeight(36, settings.density) },
    },
  };
}

/**
 * `--fn-*` custom properties for the LESS-driven surfaces. Only emitted keys the
 * user actually changed, so the untouched default writes nothing.
 */
export function cssVars(settings: AppearanceSettings): Record<string, string> {
  const vars: Record<string, string> = {};
  const radius = radiusPx(settings);
  if (radius !== null) {
    vars["--fn-radius-xs"] = `${Math.max(0, radius - 4)}px`;
    vars["--fn-radius-sm"] = `${Math.max(0, radius - 2)}px`;
    vars["--fn-radius-md"] = `${radius}px`;
    vars["--fn-radius-lg"] = `${radius + 2}px`;
    vars["--fn-radius-round"] = `${Math.max(radius, 999)}px`;
  }
  if (settings.fontSize !== "standard") {
    vars["--fn-text-2xs"] = `${scaledFontSize(FONT_SIZE["2xs"], settings.fontSize)}px`;
    vars["--fn-text-xs"] = `${scaledFontSize(FONT_SIZE.xs, settings.fontSize)}px`;
    vars["--fn-text-sm"] = `${scaledFontSize(FONT_SIZE.sm, settings.fontSize)}px`;
    vars["--fn-text-md"] = `${scaledFontSize(FONT_SIZE.md, settings.fontSize)}px`;
    vars["--fn-text-lg"] = `${scaledFontSize(FONT_SIZE.lg, settings.fontSize)}px`;
    vars["--fn-text-xl"] = `${scaledFontSize(FONT_SIZE.xl, settings.fontSize)}px`;
  }
  if (settings.fontFamily !== "system") {
    vars["--fn-font-sans"] = FONT_STACKS[settings.fontFamily];
  }
  if (settings.density !== "standard") {
    vars["--fn-density-row"] = `${scaledControlHeight(CONTROL_HEIGHT.md, settings.density)}px`;
    vars["--fn-space-sm"] = `${scaledControlHeight(12, settings.density)}px`;
    vars["--fn-space-md"] = `${scaledControlHeight(16, settings.density)}px`;
  }
  return vars;
}
