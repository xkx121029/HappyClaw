import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useBaoSettings } from "../../components/Bao/useBaoData";
import {
  DEFAULT_MASCOT_APPEARANCE,
  syncMascotAppearance,
  type MascotAppearance,
} from "../../components/Mascot/appearance";
import type { MascotInk, MascotShape } from "../../components/Mascot";

/**
 * Bao's single source of truth for the mobile tree.
 *
 * Reads the same server settings the desktop Bao surface uses, mirrors them
 * into the shared mascot store so every ``<Mascot>`` paints the same look, and
 * exposes the saved name. Never draw a bespoke mascot here.
 */
export function useBaoAppearance(enabled = true) {
  const { t } = useTranslation();
  const { settings, update } = useBaoSettings(enabled);

  const appearance = useMemo<MascotAppearance>(
    () => ({
      shape: (settings?.shape ??
        DEFAULT_MASCOT_APPEARANCE.shape) as MascotShape,
      color: (settings?.color ?? DEFAULT_MASCOT_APPEARANCE.color) as MascotInk,
      bodyColor: settings?.body_color ?? null,
      eyeColor: settings?.eye_color ?? null,
      followTheme: settings?.follow_theme ?? false,
    }),
    [settings],
  );

  useEffect(() => {
    if (settings) syncMascotAppearance(appearance);
  }, [appearance, settings]);

  return {
    settings,
    update,
    appearance,
    name: settings?.name?.trim() || t("mobile.bao.defaultName", "宝"),
  };
}
