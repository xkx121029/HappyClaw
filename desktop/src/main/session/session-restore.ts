import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

/**
 * Crash recovery for the single window.
 *
 * The shell keeps the last in-app URL and a "clean exit" flag. A launch that
 * finds the flag still `false` knows the previous process died without a quit
 * (crash, power loss, task manager) and reopens that conversation instead of
 * dropping the user on the home screen.
 */

export interface SessionSnapshot {
  url: string | null;
  cleanExit: boolean;
}

const DEFAULTS: SessionSnapshot = { url: null, cleanExit: true };

/** Must match `DASHBOARD_THEME_QUERY` in `windows/chrome.ts`. */
const THEME_QUERY = "octopTheme";

/** Sign-in and server-initialisation walls are never worth restoring. */
const SKIP_PREFIXES = ["/login", "/invite", "/setup"];

export function readSessionSnapshot(filePath: string): SessionSnapshot {
  if (!existsSync(filePath)) return { ...DEFAULTS };
  try {
    const raw = JSON.parse(readFileSync(filePath, "utf8")) as Record<string, unknown>;
    return {
      url: typeof raw.url === "string" && raw.url ? raw.url : null,
      cleanExit: raw.cleanExit === true,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function writeSessionSnapshot(
  filePath: string,
  snapshot: SessionSnapshot,
): void {
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, JSON.stringify(snapshot, null, 2), "utf8");
}

/** Only URLs on this app's own origin may be loaded back. */
export function isRestorableUrl(url: string, appOrigin: string): boolean {
  if (url !== appOrigin && !url.startsWith(`${appOrigin}/`) && !url.startsWith(`${appOrigin}?`)) {
    return false;
  }
  try {
    const { pathname } = new URL(url);
    return !SKIP_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
  } catch {
    return false;
  }
}

/**
 * The URL to boot into after an unclean exit, or `null` when the previous
 * session ended cleanly / never got past the splash.
 */
export function recoveryUrl(
  snapshot: SessionSnapshot,
  appOrigin: string,
  theme: "system" | "light" | "dark",
): string | null {
  if (snapshot.cleanExit || !snapshot.url) return null;
  if (!isRestorableUrl(snapshot.url, appOrigin)) return null;
  try {
    const parsed = new URL(snapshot.url);
    // The splash cannot read the Dashboard's localStorage, so the theme still
    // has to ride the URL on a restored path.
    parsed.searchParams.set(THEME_QUERY, theme);
    return parsed.toString();
  } catch {
    return null;
  }
}
