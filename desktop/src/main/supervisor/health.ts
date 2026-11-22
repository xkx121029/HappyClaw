/**
 * Sidecar readiness check (§3.3). Readiness is decided ONLY by a successful
 * ``/api/health`` response matching the Octop contract — never by log text.
 */

export interface HealthResponse {
  ok: boolean;
}

/**
 * Cold import of the bundled Windows runtime has been observed at about 75s
 * before ``/api/health`` answers, and real first runs have needed over 4
 * minutes. The default is deliberately wider than the worst measured cold
 * start; ``HAPPYCLAW_READY_TIMEOUT_MS`` overrides it between 30s and 15min.
 */
export const DEFAULT_HEALTH_TIMEOUT_MS = 300_000;
export const MAX_HEALTH_TIMEOUT_MS = 900_000;
const MIN_HEALTH_TIMEOUT_MS = 30_000;
export const READY_TIMEOUT_ENV = "HAPPYCLAW_READY_TIMEOUT_MS";
const POLL_INTERVAL_MS = 250;

/** Readiness budget in ms: env override, clamped, or the measured default. */
export function resolveHealthTimeoutMs(env: NodeJS.ProcessEnv = process.env): number {
  const raw = (env[READY_TIMEOUT_ENV] ?? "").trim();
  if (!raw) return DEFAULT_HEALTH_TIMEOUT_MS;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return DEFAULT_HEALTH_TIMEOUT_MS;
  return Math.min(Math.max(Math.floor(parsed), MIN_HEALTH_TIMEOUT_MS), MAX_HEALTH_TIMEOUT_MS);
}

export interface HealthProbe {
  (): Promise<{ ok: boolean; body?: unknown }>;
}

/** Validate the shape of an Octop ``/api/health`` JSON body. */
export function isHealthyBody(body: unknown): boolean {
  if (body === null || typeof body !== "object") return false;
  const record = body as Record<string, unknown>;
  return record.ok === true;
}

export async function waitForHealth(
  probe: HealthProbe,
  options: {
    timeoutMs?: number;
    intervalMs?: number;
    onExit?: () => boolean;
  } = {},
): Promise<boolean> {
  const timeoutMs = options.timeoutMs ?? resolveHealthTimeoutMs();
  const intervalMs = options.intervalMs ?? POLL_INTERVAL_MS;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (options.onExit && options.onExit()) return false;
    try {
      const result = await probe();
      if (result.ok && isHealthyBody(result.body)) return true;
    } catch {
      // Not ready yet — keep polling until the deadline.
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}
