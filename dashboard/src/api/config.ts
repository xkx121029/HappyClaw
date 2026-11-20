import { resolveWsUrl } from "../utils/desktopWsUrl";
import { routerBasename } from "../utils/publicUrl";
import { mobileApiBase, mobileCredentialToken } from "../utils/mobileEndpoint";

declare const BASE_URL: string;

/**
 * Origin every API call is based on.
 *
 * Desktop (and a phone that has not connected yet) uses the page origin /
 * build-time base. A connected phone rebases to the server address it entered
 * on the connect screen — the client may be hosted somewhere else entirely.
 */
function apiOrigin(): string {
  return mobileApiBase() ?? (BASE_URL || routerBasename() || "");
}

/**
 * Get the full API URL with /api prefix
 * @param path - API path (e.g., "/models", "/skills")
 * @returns Full API URL (e.g., "http://localhost:8088/api/models" or "/api/models")
 */
export function getApiUrl(path: string): string {
  const base = apiOrigin();
  const apiPrefix = "/api";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${apiPrefix}${normalizedPath}`;
}

/**
 * Get a WebSocket URL derived from the same origin as the API.
 * Converts http:// → ws:// and https:// → wss://.
 * If BASE_URL is empty (same-origin), uses the current page location.
 *
 * Pass the caller's own query parameters here instead of appending ``?...``
 * to the result: browser WebSockets cannot set headers, so a connected phone
 * also needs its access credential in the query string, and this function is
 * the only place that can merge both correctly.
 * @param path - API path (e.g., "/browser-stream/ws")
 * @param params - extra query parameters (token, ids, …)
 * @returns Full WebSocket URL
 */
export function getWsUrl(path: string, params?: URLSearchParams): string {
  const base = apiOrigin();
  const apiPrefix = "/api";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const query = new URLSearchParams(params);
  const credential = mobileCredentialToken();
  if (credential && !query.has("octop_token")) {
    query.set("octop_token", credential);
  }
  const qs = query.toString();
  let httpUrl = `${base}${apiPrefix}${normalizedPath}`;
  if (qs) {
    httpUrl += `${httpUrl.includes("?") ? "&" : "?"}${qs}`;
  }

  if (httpUrl.startsWith("http://")) {
    return httpUrl.replace("http://", "ws://");
  }
  if (httpUrl.startsWith("https://")) {
    return httpUrl.replace("https://", "wss://");
  }

  // Relative URL — derive from the page origin, or from the shell's relay when
  // the page is served by the desktop shell (§5.2).
  return resolveWsUrl(httpUrl);
}
