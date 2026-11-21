import type { ComponentType } from "react";
import type { OctopPluginUIHost } from "./toolRendererTypes";

/**
 * Plugin UI surface contract v1.
 *
 * The surface code runs as same-origin trusted ESM in the Dashboard page; it
 * is **not** sandboxed. See ``docs/plugin-ui-surfaces.md``.
 */
export const PLUGIN_UI_API_VERSION = 1 as const;

export const SURFACE_SLOTS = [
  "home.sidebar",
  "chat.messages.top",
  "conversation.view",
  "conversation.input.left",
  "conversation.input.overlay",
  "settings.section",
] as const;
export type SurfaceSlot = (typeof SURFACE_SLOTS)[number];

export function isSurfaceSlot(value: string): value is SurfaceSlot {
  return (SURFACE_SLOTS as readonly string[]).includes(value);
}

/** Message shape handed to ``conversation.view`` surfaces. */
export interface SurfaceMessage {
  id: string;
  role: string;
  /** Markdown/plain text as the host received it. */
  content?: unknown;
  createdAt?: string | number | null;
}

/**
 * Per-mount context. Only ``conversation.view`` fills ``message``; the other
 * slots receive the current agent/thread when the host knows them.
 */
export interface SurfaceContext {
  agentId?: string | null;
  threadId?: string | null;
  message?: SurfaceMessage;
}

export interface SurfaceProps {
  host: OctopPluginUIHost;
  pluginId: string;
  surfaceId: string;
  title: string;
  context?: SurfaceContext;
}

export interface SurfaceRegistration {
  id: string;
  slot: SurfaceSlot;
  title?: string;
  /** Ascending; defaults to 100. */
  order?: number;
  component: ComponentType<SurfaceProps>;
}

export interface RegisteredSurface extends SurfaceRegistration {
  pluginId: string;
  title: string;
  order: number;
  host: OctopPluginUIHost;
}

export type DataDomain =
  | "runtime.activity"
  | "sessions.running"
  | "plugins.installed"
  | "host.context";

export const DATA_DOMAINS: readonly DataDomain[] = [
  "runtime.activity",
  "sessions.running",
  "plugins.installed",
  "host.context",
];

export function isDataDomain(value: string): value is DataDomain {
  return (DATA_DOMAINS as readonly string[]).includes(value);
}

export interface RunningSession {
  agent_id: string;
  agent_name: string;
  thread_id: string;
  title: string;
  turn_active: boolean;
  awaiting_user: boolean;
  /** Epoch milliseconds; 0 when unknown. */
  last_active: number;
  model_ref: string | null;
}

export interface SessionsSnapshot {
  updated_at: number;
  sessions: RunningSession[];
}

export interface InstalledPluginsSnapshot {
  plugins: unknown[];
}

export interface HostContextSnapshot {
  locale: string;
  theme: "light" | "dark";
  now: number;
}

export type ProductEventName =
  | "session.started"
  | "session.updated"
  | "session.ended";

export const PRODUCT_EVENTS: readonly ProductEventName[] = [
  "session.started",
  "session.updated",
  "session.ended",
];

export function isProductEvent(value: string): value is ProductEventName {
  return (PRODUCT_EVENTS as readonly string[]).includes(value);
}
