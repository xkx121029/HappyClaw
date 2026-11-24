import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

/**
 * Last-location restore for the single window.
 *
 * The shell records the last in-app URL (and the chat session id it contained)
 * on every navigation. A relaunch reopens that exact page — same conversation —
 * instead of dropping the user on the home screen. ``cleanExit`` only records
 * whether the previous process quit in an orderly way; it no longer decides
 * whether the location is restored.
 */

export interface SessionSnapshot {
  url: string | null;
  cleanExit: boolean;
  /** Chat session id parsed from ``url`` at write time; null outside a chat. */
  sessionId: string | null;
}

const DEFAULTS: SessionSnapshot = { url: null, cleanExit: true, sessionId: null };

/** Must match `DASHBOARD_THEME_QUERY` in `windows/chrome.ts`. */
const THEME_QUERY = "happyclawTheme";

/** Sign-in and server-initialisation walls are never worth restoring. */
const SKIP_PREFIXES = ["/login", "/invite", "/setup"];

export interface ChatLocation {
  agentId: string;
  sessionId: string | null;
}

export function readSessionSnapshot(filePath: string): SessionSnapshot {
  if (!existsSync(filePath)) return { ...DEFAULTS };
  try {
    const raw = JSON.parse(readFileSync(filePath, "utf8")) as Record<string, unknown>;
    return {
      url: typeof raw.url === "string" && raw.url ? raw.url : null,
      cleanExit: raw.cleanExit === true,
      sessionId: typeof raw.sessionId === "string" && raw.sessionId ? raw.sessionId : null,
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
  if (!isAppUrl(url, appOrigin)) return false;
  try {
    const { pathname } = new URL(url);
    return !SKIP_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
  } catch {
    return false;
  }
}

function isAppUrl(url: string, appOrigin: string): boolean {
  return (
    url === appOrigin || url.startsWith(`${appOrigin}/`) || url.startsWith(`${appOrigin}?`)
  );
}

/**
 * The page to boot into after a relaunch, or `null` when nothing usable was
 * recorded (first launch, sign-in wall, setup wall) and the normal entry applies.
 */
export function restoreUrl(
  snapshot: SessionSnapshot,
  appOrigin: string,
  theme: "system" | "light" | "dark",
): string | null {
  if (!snapshot.url) return null;
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

/**
 * Split a ``/chat/<agent>[/<session>]`` URL. Returns `null` outside the chat
 * route so the restore path can leave other pages untouched.
 */
export function chatLocation(url: string, appOrigin: string): ChatLocation | null {
  if (!isAppUrl(url, appOrigin)) return null;
  try {
    const segments = new URL(url).pathname.split("/").filter(Boolean);
    if (segments[0] !== "chat") return null;
    const agentId = segments[1] ? decodeURIComponent(segments[1]) : "";
    if (!agentId) return null;
    const sessionId = segments[2] ? decodeURIComponent(segments[2]) : null;
    return { agentId, sessionId: sessionId || null };
  } catch {
    return null;
  }
}

/** The chat session id carried by ``url``, or null when it is not a chat URL. */
export function sessionIdOf(url: string, appOrigin: string): string | null {
  return chatLocation(url, appOrigin)?.sessionId ?? null;
}

/**
 * Route-only fallback for a chat whose session no longer exists: keep the agent
 * page, drop the stale session id, and carry the theme like any restore.
 */
export function routeOnlyUrl(
  url: string,
  appOrigin: string,
  theme: "system" | "light" | "dark",
): string | null {
  const chat = chatLocation(url, appOrigin);
  if (!chat?.sessionId) return null;
  try {
    const parsed = new URL(url);
    parsed.pathname = `/chat/${encodeURIComponent(chat.agentId)}`;
    parsed.searchParams.set(THEME_QUERY, theme);
    return parsed.toString();
  } catch {
    return null;
  }
}
