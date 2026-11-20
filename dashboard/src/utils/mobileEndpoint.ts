/**
 * Mobile client connection to a HappyClaw server.
 *
 * Phones never assume same-origin: the client may be hosted anywhere, so the
 * user types the server's access URL once and every API/WS call is rebased.
 * Desktop keeps the existing same-origin behaviour (the saved endpoint is
 * ignored when the viewport is not a phone one).
 */

export const MOBILE_BREAKPOINT = 768;
/** Minimum server protocol this client understands (see /api/health). */
export const MIN_API_PROTOCOL = 2;
export const ACCESS_TOKEN_HEADER = "X-Octop-Token";

const STORAGE_KEY = "octop:mobile-connection";
const PROBE_TIMEOUT_MS = 8000;
const CREDENTIAL_TIMEOUT_MS = 10000;

export interface MobileConnection {
  /** Normalized origin, no trailing slash (e.g. http://192.168.1.10:8088). */
  baseUrl: string;
  /** Optional access credential; empty when the server does not require one. */
  token?: string;
  /** Server build identifier captured at connect time (display only). */
  serverVersion?: string;
  connectedAt: number;
}

export type ConnectErrorCode =
  | "invalid_url"
  | "timeout"
  | "network"
  | "unauthorized"
  | "version_mismatch"
  | "server_error"
  | "not_happyclaw";

export class ConnectError extends Error {
  code: ConnectErrorCode;
  detail?: string;

  constructor(code: ConnectErrorCode, detail?: string) {
    super(code);
    this.name = "ConnectError";
    this.code = code;
    this.detail = detail;
  }
}

/** True on phone-sized viewports; false during SSR/tests without matchMedia. */
export function isMobileViewport(): boolean {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return false;
  }
  return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`).matches;
}

/**
 * Normalize what the user typed into an origin.
 * Accepts ``192.168.1.10:8088`` (scheme defaults to http) and strips a
 * trailing slash, path, query and hash — the client only needs an origin.
 */
export function normalizeEndpointInput(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) throw new ConnectError("invalid_url");
  if (/\s/.test(trimmed)) throw new ConnectError("invalid_url", trimmed);

  const withScheme = /^[a-zA-Z][a-zA-Z\d+.-]*:\/\//.test(trimmed)
    ? trimmed
    : `http://${trimmed}`;

  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    throw new ConnectError("invalid_url", trimmed);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ConnectError("invalid_url", trimmed);
  }
  if (!url.hostname) throw new ConnectError("invalid_url", trimmed);
  return url.origin;
}

export function readConnection(): MobileConnection | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<MobileConnection>;
    if (!parsed || typeof parsed.baseUrl !== "string") return null;
    const baseUrl = normalizeEndpointInput(parsed.baseUrl);
    return {
      baseUrl,
      token: typeof parsed.token === "string" ? parsed.token : undefined,
      serverVersion:
        typeof parsed.serverVersion === "string"
          ? parsed.serverVersion
          : undefined,
      connectedAt:
        typeof parsed.connectedAt === "number"
          ? parsed.connectedAt
          : Date.now(),
    };
  } catch {
    return null;
  }
}

export function saveConnection(connection: MobileConnection): void {
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      baseUrl: normalizeEndpointInput(connection.baseUrl),
      token: connection.token || undefined,
      serverVersion: connection.serverVersion,
      connectedAt: connection.connectedAt,
    }),
  );
}

export function clearConnection(): void {
  window.localStorage.removeItem(STORAGE_KEY);
  window.sessionStorage.removeItem(CONNECT_DRAFT_KEY);
}

/** Draft address shown on the connect screen after "switch server". */
const CONNECT_DRAFT_KEY = "octop:mobile-connect-draft";

export function writeConnectDraft(baseUrl: string): void {
  window.sessionStorage.setItem(CONNECT_DRAFT_KEY, baseUrl);
}

export function readConnectDraft(): string {
  return window.sessionStorage.getItem(CONNECT_DRAFT_KEY) || "";
}

/**
 * API origin override for phone clients. ``null`` means "use the page origin"
 * (desktop and any phone that has not connected yet).
 */
export function mobileApiBase(): string | null {
  if (!isMobileViewport()) return null;
  return readConnection()?.baseUrl ?? null;
}

/** Extra header for servers that require an access credential. */
export function mobileCredentialHeaders(): Record<string, string> {
  const connection = isMobileViewport() ? readConnection() : null;
  return connection?.token ? { [ACCESS_TOKEN_HEADER]: connection.token } : {};
}

/**
 * Credential for transports that cannot set headers (browser WebSockets).
 * ``null`` when this client has no saved secret.
 */
export function mobileCredentialToken(): string | null {
  if (!isMobileViewport()) return null;
  return readConnection()?.token ?? null;
}

function tokenHeaders(token?: string): Record<string, string> {
  return token ? { [ACCESS_TOKEN_HEADER]: token } : {};
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...init,
      signal: controller.signal,
      cache: "no-store",
      credentials: "omit",
    });
  } catch (error) {
    if (controller.signal.aborted) throw new ConnectError("timeout");
    // A TypeError here is a DNS failure, refused connection, mixed content,
    // or a CORS rejection — all indistinguishable to fetch.
    throw new ConnectError("network", (error as Error)?.message);
  } finally {
    clearTimeout(timer);
  }
}

export interface ProbeResult {
  baseUrl: string;
  serverVersion?: string;
  protocol: number;
  /** True when the entered credential was accepted (server requires auth). */
  credentialAccepted: boolean;
}

/** Subset of ``GET /api/health`` the connect screen relies on. */
interface HealthPayload {
  ok?: boolean;
  api_protocol?: number;
  build?: { git_commit?: string; dashboard_built_at?: string };
}

/**
 * Probe ``/api/health`` then validate the credential against a protected
 * endpoint, so the caller can tell "wrong address" from "wrong token".
 */
export async function probeConnection(
  rawUrl: string,
  token?: string,
): Promise<ProbeResult> {
  const baseUrl = normalizeEndpointInput(rawUrl);
  const response = await fetchWithTimeout(
    `${baseUrl}/api/health`,
    { headers: { Accept: "application/json", ...tokenHeaders(token) } },
    PROBE_TIMEOUT_MS,
  );

  if (response.status === 401 || response.status === 403) {
    throw new ConnectError("unauthorized");
  }
  if (!response.ok) {
    throw new ConnectError("server_error", String(response.status));
  }

  let payload: HealthPayload | null = null;
  try {
    payload = (await response.json()) as HealthPayload;
  } catch {
    payload = null;
  }
  if (!payload || payload.ok !== true) {
    throw new ConnectError("not_happyclaw");
  }

  const protocol = Number(payload.api_protocol ?? 1);
  if (!Number.isFinite(protocol) || protocol < MIN_API_PROTOCOL) {
    throw new ConnectError("version_mismatch", `server=${protocol}`);
  }

  // Health is intentionally public. A protected endpoint tells us whether the
  // credential is actually accepted (and 401 here is a credential problem).
  const guarded = await fetchWithTimeout(
    `${baseUrl}/api/agents`,
    { headers: { Accept: "application/json", ...tokenHeaders(token) } },
    CREDENTIAL_TIMEOUT_MS,
  );
  if (guarded.status === 401 || guarded.status === 403) {
    throw new ConnectError("unauthorized");
  }
  if (guarded.status >= 500) {
    throw new ConnectError("server_error", String(guarded.status));
  }
  if (!guarded.ok) {
    throw new ConnectError("server_error", String(guarded.status));
  }

  const commit = payload.build?.git_commit;
  return {
    baseUrl,
    serverVersion: typeof commit === "string" ? commit.slice(0, 8) : undefined,
    protocol,
    credentialAccepted: Boolean(token),
  };
}
