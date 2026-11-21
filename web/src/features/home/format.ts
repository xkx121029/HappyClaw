import { useTranslation } from "react-i18next";

import { formatRelativeTime, formatTime } from "@/lib/format";

/**
 * Compact token counts. Home never shows raw 7-digit numbers: 1.2M reads at a
 * glance, 1,234,567 does not.
 */
export function formatTokens(value: number, locale: string): string {
  return new Intl.NumberFormat(locale === "en" ? "en" : "zh", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function useActivityTime() {
  const { i18n } = useTranslation();
  return (epochSeconds: number | undefined) =>
    formatTime(epochSeconds, undefined) || formatRelativeTime(epochSeconds, i18n.language);
}
