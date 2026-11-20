import { request } from "../../api/request";
import { runtimeApi } from "../../api/modules/runtime";
import { octopThreadsApi } from "../../api/modules/octopThreads";
import { pluginsApi } from "../../api/modules/plugins";
import type { OctopAgent } from "../../context/AgentContext";
import i18n from "../../i18n";
import {
  isDataDomain,
  isProductEvent,
  type DataDomain,
  type HostContextSnapshot,
  type ProductEventName,
  type RunningSession,
  type SessionsSnapshot,
} from "./types";

const SESSION_POLL_MS = 3_000;
const ACTIVITY_POLL_MS = 3_000;
const PLUGINS_POLL_MS = 10_000;

type Listener = (value: unknown) => void;
type EventListener = (payload: unknown) => void;

const dataSubs = new Map<DataDomain, Set<Listener>>();
const timers = new Map<DataDomain, number>();
const lastJson = new Map<DataDomain, string>();
const eventSubs = new Map<ProductEventName, Set<EventListener>>();

let previousSessions = new Map<string, RunningSession>();
let sessionsInitialized = false;

function readTheme(): "light" | "dark" {
  if (typeof document === "undefined") return "light";
  if (document.documentElement.getAttribute("data-theme") === "dark") {
    return "dark";
  }
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function normalizeTimestamp(value: number | null | undefined): number {
  if (!value || !Number.isFinite(value) || value <= 0) return 0;
  return value < 1_000_000_000_000 ? value * 1000 : value;
}

function hostContext(): HostContextSnapshot {
  return {
    locale: i18n.language || "zh",
    theme: readTheme(),
    now: Date.now(),
  };
}

async function fetchSessions(): Promise<SessionsSnapshot> {
  const agents = await request<OctopAgent[]>("/agents");
  const runningAgents = agents.filter(
    (agent) => agent.state === "running" || Boolean(agent.bridge_disconnected),
  );
  const results = await Promise.allSettled(
    runningAgents.map(async (agent) => {
      const threads = await octopThreadsApi.list(agent.agent_id, 20);
      return { agent, threads };
    }),
  );
  const sessions: RunningSession[] = [];
  for (const result of results) {
    if (result.status !== "fulfilled") continue;
    const { agent, threads } = result.value;
    for (const thread of threads) {
      const turnActive = thread.turn_active === true;
      const awaitingUser = thread.awaiting_user === true;
      if (!turnActive && !awaitingUser) continue;
      sessions.push({
        agent_id: agent.agent_id,
        agent_name: agent.name || agent.agent_id,
        thread_id: thread.thread_id,
        title: thread.title?.trim() || thread.thread_id,
        turn_active: turnActive,
        awaiting_user: awaitingUser,
        last_active: normalizeTimestamp(thread.last_active),
        model_ref: thread.model_ref ?? null,
      });
    }
  }
  sessions.sort((left, right) => {
    if (left.last_active !== right.last_active) {
      return right.last_active - left.last_active;
    }
    return left.thread_id.localeCompare(right.thread_id);
  });
  return { updated_at: Date.now(), sessions };
}

async function fetchDomain(domain: DataDomain): Promise<unknown> {
  switch (domain) {
    case "runtime.activity":
      return runtimeApi.activity();
    case "sessions.running":
      return fetchSessions();
    case "plugins.installed": {
      const plugins = await pluginsApi.list();
      return { plugins };
    }
    case "host.context":
      return hostContext();
    default:
      throw new Error(`unsupported data domain: ${String(domain)}`);
  }
}

function emitEvent(name: ProductEventName, payload: unknown): void {
  const listeners = eventSubs.get(name);
  if (!listeners) return;
  for (const listener of [...listeners]) {
    try {
      listener(payload);
    } catch {
      /* a broken plugin must not break the event bus */
    }
  }
}

function sessionKey(session: RunningSession): string {
  return `${session.agent_id}\0${session.thread_id}`;
}

function diffSessions(next: RunningSession[]): void {
  const nextMap = new Map<string, RunningSession>();
  for (const session of next) nextMap.set(sessionKey(session), session);
  if (sessionsInitialized) {
    const at = Date.now();
    for (const [key, session] of nextMap) {
      const previous = previousSessions.get(key);
      if (!previous) {
        emitEvent("session.started", { at, session });
      } else if (JSON.stringify(previous) !== JSON.stringify(session)) {
        emitEvent("session.updated", { at, session });
      }
    }
    for (const [key, session] of previousSessions) {
      if (!nextMap.has(key)) {
        emitEvent("session.ended", { at, session_id: session.thread_id });
      }
    }
  }
  previousSessions = nextMap;
  sessionsInitialized = true;
}

function notify(domain: DataDomain, value: unknown): void {
  const serialized = JSON.stringify(value);
  if (lastJson.get(domain) === serialized) return;
  lastJson.set(domain, serialized);
  const listeners = dataSubs.get(domain);
  if (!listeners) return;
  for (const listener of [...listeners]) {
    try {
      listener(value);
    } catch {
      /* ignore one broken subscriber */
    }
  }
}

async function refresh(domain: DataDomain): Promise<void> {
  if (typeof document !== "undefined" && document.hidden) return;
  try {
    const value = await fetchDomain(domain);
    if (domain === "sessions.running") {
      diffSessions((value as SessionsSnapshot).sessions);
    }
    notify(domain, value);
  } catch (err) {
    console.warn(`[plugin-ui] data ${domain} refresh failed:`, err);
  }
}

function sessionEventInterest(): boolean {
  return (
    (eventSubs.get("session.started")?.size ?? 0) > 0 ||
    (eventSubs.get("session.updated")?.size ?? 0) > 0 ||
    (eventSubs.get("session.ended")?.size ?? 0) > 0
  );
}

function intervalFor(domain: DataDomain): number | null {
  switch (domain) {
    case "runtime.activity":
      return ACTIVITY_POLL_MS;
    case "sessions.running":
      return SESSION_POLL_MS;
    case "plugins.installed":
      return PLUGINS_POLL_MS;
    case "host.context":
      return null;
    default:
      return null;
  }
}

function syncTimer(domain: DataDomain): void {
  const interested =
    (dataSubs.get(domain)?.size ?? 0) > 0 ||
    (domain === "sessions.running" && sessionEventInterest());
  const current = timers.get(domain);
  if (!interested) {
    if (current !== undefined) {
      window.clearInterval(current);
      timers.delete(domain);
    }
    return;
  }
  const interval = intervalFor(domain);
  if (interval === null) return;
  if (current !== undefined) return;
  void refresh(domain);
  timers.set(
    domain,
    window.setInterval(() => void refresh(domain), interval),
  );
}

export function readPluginData<T = unknown>(domain: string): Promise<T> {
  if (!isDataDomain(domain)) {
    return Promise.reject(new Error(`unsupported data domain: ${domain}`));
  }
  return fetchDomain(domain) as Promise<T>;
}

export function subscribePluginData<T = unknown>(
  domain: string,
  cb: (value: T) => void,
): () => void {
  if (!isDataDomain(domain)) {
    throw new Error(`unsupported data domain: ${domain}`);
  }
  const typed = domain as DataDomain;
  let listeners = dataSubs.get(typed);
  if (!listeners) {
    listeners = new Set();
    dataSubs.set(typed, listeners);
  }
  const listener = cb as Listener;
  listeners.add(listener);
  syncTimer(typed);
  // Late subscribers get the last known value immediately when available.
  const cached = lastJson.get(typed);
  if (cached) {
    try {
      listener(JSON.parse(cached));
    } catch {
      /* ignore malformed cache (should not happen) */
    }
  }
  let disposed = false;
  return () => {
    if (disposed) return;
    disposed = true;
    const current = dataSubs.get(typed);
    if (!current) return;
    current.delete(listener);
    if (current.size === 0) dataSubs.delete(typed);
    syncTimer(typed);
  };
}

export function subscribePluginEvent<T = unknown>(
  event: string,
  cb: (payload: T) => void,
): () => void {
  if (!isProductEvent(event)) {
    throw new Error(`unsupported product event: ${event}`);
  }
  const typed = event as ProductEventName;
  let listeners = eventSubs.get(typed);
  if (!listeners) {
    listeners = new Set();
    eventSubs.set(typed, listeners);
  }
  const listener = cb as EventListener;
  listeners.add(listener);
  // Session events need the poller even when nobody reads the data domain.
  syncTimer("sessions.running");
  let disposed = false;
  return () => {
    if (disposed) return;
    disposed = true;
    const current = eventSubs.get(typed);
    if (!current) return;
    current.delete(listener);
    if (current.size === 0) eventSubs.delete(typed);
    syncTimer("sessions.running");
  };
}

/** Test helper: drop every subscription and timer. */
export function resetPluginDataBus(): void {
  for (const timer of timers.values()) window.clearInterval(timer);
  timers.clear();
  dataSubs.clear();
  eventSubs.clear();
  lastJson.clear();
  previousSessions = new Map();
  sessionsInitialized = false;
}

export function isPluginDataDomain(value: string): boolean {
  return isDataDomain(value);
}
