/**
 * Time formatting for a UI that may run in a different timezone than the
 * server. Every function takes the server timezone when the caller has it
 * (from `GET /api/settings/timezone`) and falls back to the browser's own.
 */

export function formatDateTime(
  epochSeconds: number | undefined,
  timeZone: string | undefined,
): string {
  if (!epochSeconds) return "";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(new Date(epochSeconds * 1000));
}

export function formatTime(
  epochSeconds: number | undefined,
  timeZone: string | undefined,
): string {
  if (!epochSeconds) return "";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  }).format(new Date(epochSeconds * 1000));
}

export function formatRelativeTime(
  epochSeconds: number | undefined,
  timeZone: string | undefined,
): string {
  if (!epochSeconds) return "";
  const then = epochSeconds * 1000;
  const diffSeconds = Math.round((then - Date.now()) / 1000);
  const abs = Math.abs(diffSeconds);

  if (abs < 45) return "now";

  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (abs < 3600) return formatter.format(Math.round(diffSeconds / 60), "minute");
  if (abs < 86_400) return formatter.format(Math.round(diffSeconds / 3600), "hour");
  if (abs < 604_800) return formatter.format(Math.round(diffSeconds / 86_400), "day");
  if (abs < 2_419_200) {
    return formatter.format(Math.round(diffSeconds / 604_800), "week");
  }
  return formatDateTime(epochSeconds, timeZone);
}
