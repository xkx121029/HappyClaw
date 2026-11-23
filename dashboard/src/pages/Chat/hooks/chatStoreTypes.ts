/**
 * Shared types for the chat store: event payloads, listener signatures and the live-socket descriptor.
 */

import { type ChatAttachment } from "./sseHelpers";

// ── Tool / stream event hooks (for cross-module bridging) ──
export type ToolEventKind = "toolStart" | "toolDone";

export interface ToolEvent {
  kind: ToolEventKind;
  sessionId: string;
  toolName: string;
  toolId: string;
}

export type StreamEventKind = "streamStart" | "streamEnd" | "streamResume";

export interface StreamEvent {
  kind: StreamEventKind;
  sessionId: string;
}

export type SlashActionEvent = {
  action: string;
  agent_id?: string;
  sessionId?: string;
  mode?: string;
};

export type ToolEventListener = (event: ToolEvent) => void;

export type StreamEventListener = (event: StreamEvent) => void;

export type SlashActionListener = (event: SlashActionEvent) => void;

// Session lifecycle events (e.g. deletion) for cross-module bridging.
export type SessionEventKind =
  | "sessionDeleted"
  | "sessionsChanged"
  | "sessionRenamed";

export interface SessionEvent {
  kind: SessionEventKind;
  sessionId: string;
  /** Owning agent, when the event comes from a server push. */
  agentId?: string;
  /** New thread title from a ``thread_title`` frame. */
  title?: string;
  /** Local clipped question shown until the server title arrives. */
  provisional?: boolean;
}

export type SessionEventListener = (event: SessionEvent) => void;

export type LiveSocket = {
  ws: WebSocket;
  agentId: string;
  threadId: string;
  /**
   * Socket was closed on purpose (replace / done / user stop). Unexpected drop
   * is false so auto-resume can re-subscribe.
   */
  intentionalClose: boolean;
  /**
   * User hit stop (or cancelStream). Distinct from intentional socket *replace*
   * while the server turn should keep running.
   */
  userCancelled: boolean;
  /** Subscribe-only socket — replacing it must not send `cancel` to the host. */
  listenOnly?: boolean;
  pingTimer?: ReturnType<typeof setInterval>;
};

export interface SteerRestoreEvent {
  sessionId: string;
  text: string;
  attachments?: ChatAttachment[];
  reason: string;
  /** False announces the outcome without putting the draft back. */
  applyToComposer?: boolean;
}

export interface SharedTurnBusyEvent {
  sessionId: string;
  messageId: string;
}
