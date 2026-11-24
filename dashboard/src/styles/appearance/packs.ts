/**
 * Theme packs: named combinations of the individual knobs.
 *
 * A pack is a preset, not a mode — picking one writes the same fields the
 * individual controls write, so the user can pick "instrument" and then loosen
 * the radius by hand. `default` writes nothing at all.
 */

import type { ThemePalette } from "../themePalettes";
import type { ThemePreference } from "../appearanceStorage";

import { DEFAULT_APPEARANCE, type AppearanceSettings, type ThemePack } from "./settings";

export interface PackDefinition {
  id: ThemePack;
  /** Settings the pack writes. Packs never touch custom CSS. */
  settings: AppearanceSettings;
  palette: ThemePalette;
  preference: ThemePreference;
}

export const PACKS: Record<ThemePack, PackDefinition> = {
  default: {
    id: "default",
    settings: { ...DEFAULT_APPEARANCE },
    palette: "rose",
    preference: "system",
  },
  instrument: {
    id: "instrument",
    settings: {
      ...DEFAULT_APPEARANCE,
      pack: "instrument",
      radius: "0",
      density: "compact",
      fontFamily: "system",
    },
    palette: "slate",
    preference: "dark",
  },
  warmPaper: {
    id: "warmPaper",
    settings: {
      ...DEFAULT_APPEARANCE,
      pack: "warmPaper",
      radius: "12",
      density: "comfortable",
      fontFamily: "serif",
    },
    palette: "amber",
    preference: "light",
  },
  highContrast: {
    id: "highContrast",
    settings: {
      ...DEFAULT_APPEARANCE,
      pack: "highContrast",
      radius: "4",
      density: "standard",
      fontFamily: "system",
    },
    palette: "slate",
    preference: "light",
  },
};

export function packOf(id: ThemePack): PackDefinition {
  return PACKS[id] ?? PACKS.default;
}
