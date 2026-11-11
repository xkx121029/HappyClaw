/**
 * "Back up now" from the tray / Help menu.
 *
 * The shell calls the normal backup endpoint, so a tray backup is the same
 * archive the settings page produces. Chat history is included: for a
 * single-user personal tool that is the part worth protecting.
 *
 * A device JWT is optional: the single-user sidecar accepts an empty token, so
 * a fresh install can back up before any device credential exists.
 */

export interface ManualBackupResult {
  ok: boolean;
  name: string | null;
  size: number | null;
  message: string | null;
}

const TIMEOUT_MS = 10 * 60 * 1000;

function errorDetail(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null) {
    const detail = (body as Record<string, unknown>).detail;
    if (typeof detail === "string" && detail) return detail;
    const message = (body as Record<string, unknown>).message;
    if (typeof message === "string" && message) return message;
  }
  return `HTTP ${status}`;
}

export async function createManualBackup(options: {
  baseUrl: string;
  /** Omit on machines without a device credential; the sidecar then runs unauthenticated. */
  token?: string | null;
  fetchImpl?: typeof fetch;
}): Promise<ManualBackupResult> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (options.token) headers.authorization = `Bearer ${options.token}`;
  try {
    const response = await fetchImpl(`${options.baseUrl}/api/backup/create`, {
      method: "POST",
      headers,
      body: JSON.stringify({ include_chats: true }),
      signal: controller.signal,
    });
    const text = await response.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    if (!response.ok) {
      return { ok: false, name: null, size: null, message: errorDetail(body, response.status) };
    }
    const record = (body ?? {}) as Record<string, unknown>;
    return {
      ok: true,
      name: typeof record.name === "string" ? record.name : null,
      size: typeof record.size === "number" ? record.size : null,
      message: null,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, name: null, size: null, message };
  } finally {
    clearTimeout(timer);
  }
}
