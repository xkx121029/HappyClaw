/**
 * The one HTTP seam the ported chat logic uses.
 *
 * `web/src/lib/api/client.ts` is the app's client: typed, with auth, error
 * mapping and token renewal already wired. The chat store, however, makes a
 * handful of calls whose payloads the backend leaves untyped (`response_model`
 * is absent on most chat routes, so the generated types are
 * `Record<string, unknown>`), plus one SSE POST that must stay a raw `fetch`
 * so its body can be consumed incrementally.
 *
 * This module keeps those two needs in one place: the same origin, the same
 * credentials, the same error envelope as `client.ts`, without the old
 * dashboard's desktop-shell / phone-credential / login-redirect plumbing
 * (`dashboard/src/api/request.ts`), which the new app does not have.
 */
import { getAuthToken } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import { env } from "@/lib/env";
import { readStored, storageKeys } from "@/lib/storage";

export { getAuthToken };

/**
 * Explicit agent-scope header for a caller that hops through the remote bridge
 * (`dashboard/src/api/request.ts#bridgeAgentHeaders`).
 */
export function bridgeAgentHeaders(agentId?: string | null): Record<string, string> | undefined {
  const id = (agentId ?? "").trim();
  if (!id) return undefined;
  return { "X-Octop-Agent-Id": id };
}

/** Agent the legacy `X-Octop-Agent-Id` header names, when a route needs it. */
let activeAgentId: string | null = null;

export function setActiveAgentId(agentId: string | null): void {
  activeAgentId = agentId;
}

/** Absolute `/api` URL for a path that already excludes the prefix. */
export function getApiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${env.apiBase}/api${normalized}`;
}

/**
 * WebSocket URL for an `/api` path. Browser sockets cannot send headers, so
 * the token goes in the query string; a relative base resolves against the
 * page origin, which is what both the Vite proxy and the same-origin
 * production build serve.
 */
export function getWsUrl(path: string, params?: URLSearchParams): string {
  const url = getApiUrl(path);
  const query = new URLSearchParams(params);
  const qs = query.toString();
  const target = qs ? `${url}${url.includes("?") ? "&" : "?"}${qs}` : url;
  const absolute = /^https?:\/\//.test(target)
    ? target
    : `${window.location.origin}${target}`;
  return absolute.replace(/^http/, "ws");
}

function buildHeaders(path: string, extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  headers.set("Accept-Language", readStored(storageKeys.locale) === "en" ? "en" : "zh");
  const token = getAuthToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (activeAgentId && !headers.has("X-Octop-Agent-Id") && path.startsWith("/agents/")) {
    headers.set("X-Octop-Agent-Id", activeAgentId);
  }
  return headers;
}

/**
 * `fetch` an `/api` path and return its JSON body, raising `ApiError` with the
 * backend's error envelope on a non-2xx response.
 */
export async function request<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(getApiUrl(path), {
    ...options,
    headers: buildHeaders(path, options.headers),
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    const body: unknown = contentType.includes("application/json")
      ? await response.json().catch(() => null)
      : await response.text().catch(() => null);
    throw ApiError.fromResponse(response.status, body);
  }

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return (await response.text()) as T;
  }
  return (await response.json()) as T;
}

/** Raw `Response` for callers that stream the body (the SSE turn resume). */
export async function requestStream(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  return fetch(getApiUrl(path), {
    ...options,
    headers: buildHeaders(path, options.headers),
  });
}

/** `fetch` an `/api` path and return its body as a Blob (trajectory export). */
export async function requestBlob(
  path: string,
  options: RequestInit = {},
): Promise<Blob> {
  const response = await fetch(getApiUrl(path), {
    ...options,
    headers: buildHeaders(path, options.headers),
  });
  if (!response.ok) throw ApiError.fromResponse(response.status, await response.text());
  return response.blob();
}

/**
 * `FormData` upload with progress. XHR rather than `fetch` because antd's
 * Uploader renders a real progress bar from `upload.onprogress`.
 */
export function requestUpload<T = unknown>(
  path: string,
  body: FormData,
  options: RequestInit = {},
  onProgress?: (loaded: number, total: number) => void,
): Promise<T> {
  // Multipart bodies must not carry a JSON content type; the browser sets the
  // boundary, so drop the header `buildHeaders` adds.
  const headers = buildHeaders(path, options.headers);
  headers.delete("Content-Type");

  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(options.method ?? "POST", getApiUrl(path));
    headers.forEach((value, key) => xhr.setRequestHeader(key, value));
    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total);
      };
    }
    xhr.onload = () => {
      let parsed: unknown;
      try {
        parsed = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        parsed = xhr.responseText;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(parsed as T);
      else reject(ApiError.fromResponse(xhr.status, parsed));
    };
    xhr.onerror = () => reject(new TypeError("Network request failed"));
    xhr.send(body);
  });
}

/**
 * Access credential a phone-hosted dashboard passes in a query string, where
 * headers are unavailable. The desktop and local builds have none.
 */
export function mobileCredentialToken(): string | null {
  return null;
}
