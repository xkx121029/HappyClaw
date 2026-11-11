/**
 * Quit guard: ask before a user-initiated quit interrupts work.
 *
 * The sidecar is the only trustworthy source of "is something running" (WS
 * connections and loaded agents are not). When the read-only activity endpoint
 * is missing or slow the guard stays out of the way: exiting must never be
 * blocked by a query.
 */

export type QuitReason = "user" | "update" | "signal";

export interface QuitGuardDecision {
  ask: boolean;
  counts: Record<string, number>;
  total: number;
  unsaved: boolean;
}

export interface QuitGuardPrompt {
  message: string;
  detail: string;
}

const DEFAULT_TIMEOUT_MS = 800;

function emptyDecision(unsaved: boolean): QuitGuardDecision {
  return { ask: unsaved, counts: {}, total: 0, unsaved };
}

function readCounts(value: unknown): Record<string, number> | null {
  if (typeof value !== "object" || value === null) return null;
  const out: Record<string, number> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) {
      out[key] = Math.trunc(raw);
    }
  }
  return out;
}

export async function inspectBeforeQuit(options: {
  reason: QuitReason;
  /** 0 = no sidecar, so there is nothing to ask. */
  backendPort: number;
  /** The Dashboard told the shell it holds unsaved work. */
  unsaved?: boolean;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}): Promise<QuitGuardDecision> {
  const unsaved = options.unsaved === true;
  if (options.reason !== "user" || options.backendPort === 0) {
    return emptyDecision(unsaved);
  }

  const fetchImpl = options.fetchImpl ?? fetch;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(
      `http://127.0.0.1:${options.backendPort}/api/runtime/activity`,
      { signal: controller.signal },
    );
    if (!response.ok) return emptyDecision(unsaved);
    const body = (await response.json()) as Record<string, unknown>;
    if (body.busy !== true) return emptyDecision(unsaved);
    const counts = readCounts(body.counts) ?? {};
    const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
    return { ask: true, counts, total: total || 1, unsaved };
  } catch {
    // Timeout, network error, or malformed JSON: unknown, so let the quit pass.
    return emptyDecision(unsaved);
  } finally {
    clearTimeout(timer);
  }
}

function isChinese(locale: string): boolean {
  return locale.toLowerCase().startsWith("zh");
}

function typeLabel(kind: string, zh: boolean): string {
  if (kind === "agent_turn") return zh ? "对话" : "conversation";
  if (kind === "terminal") return zh ? "终端会话" : "terminal session";
  return kind;
}

/** Native confirmation copy, or `null` when nothing would be lost. */
export function quitPrompt(
  decision: QuitGuardDecision,
  locale: string,
): QuitGuardPrompt | null {
  if (!decision.ask) return null;
  const zh = isChinese(locale);
  const lines: string[] = [];

  if (decision.total > 0) {
    const parts = Object.entries(decision.counts)
      .filter(([, count]) => count > 0)
      .map(([kind, count]) => `${typeLabel(kind, zh)} ${count} ${zh ? "个" : ""}`.trim());
    lines.push(
      zh
        ? `${parts.join(" · ")}。退出会中断它们。`
        : `${parts.join(" · ")}. Quitting will interrupt them.`,
    );
  }
  if (decision.unsaved) {
    lines.push(zh ? "还有未保存的内容，退出后会丢失。" : "Unsaved work will be lost.");
  }

  return {
    message:
      decision.total > 0
        ? zh
          ? `还有 ${decision.total} 个任务正在运行`
          : `${decision.total} task${decision.total === 1 ? "" : "s"} still running`
        : zh
          ? "还有未保存的内容"
          : "Unsaved work",
    detail: lines.join("\n"),
  };
}
