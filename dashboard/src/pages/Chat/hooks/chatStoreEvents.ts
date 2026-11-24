/**
 * Cross-module event buses: tool / stream / slash-action / session lifecycle, steer-restore and shared-turn-busy.
 */

import type {
  SessionEvent,
  SessionEventListener,
  SharedTurnBusyEvent,
  SlashActionEvent,
  SlashActionListener,
  SteerRestoreEvent,
  StreamEvent,
  StreamEventListener,
  ToolEvent,
  ToolEventListener,
} from "./chatStoreTypes";

export const toolEventListeners = new Set<ToolEventListener>();

export const streamEventListeners = new Set<StreamEventListener>();

export const slashActionListeners = new Set<SlashActionListener>();

/** Register a listener for tool call start/done events. Returns unsubscribe fn. */
export function onToolEvent(listener: ToolEventListener): () => void {
  toolEventListeners.add(listener);
  return () => {
    toolEventListeners.delete(listener);
  };
}

/** Register a listener for stream start/end events. Returns unsubscribe fn. */
export function onStreamEvent(listener: StreamEventListener): () => void {
  streamEventListeners.add(listener);
  return () => {
    streamEventListeners.delete(listener);
  };
}

/** Register a listener for slash_action events (e.g. switch_agent). */
export function onSlashAction(listener: SlashActionListener): () => void {
  slashActionListeners.add(listener);
  return () => {
    slashActionListeners.delete(listener);
  };
}

export function emitToolEvent(event: ToolEvent) {
  for (const fn of toolEventListeners) {
    try {
      fn(event);
    } catch {
      /* ignore */
    }
  }
}

export function emitStreamEvent(event: StreamEvent) {
  for (const fn of streamEventListeners) {
    try {
      fn(event);
    } catch {
      /* ignore */
    }
  }
}

export function emitSlashAction(event: SlashActionEvent) {
  for (const fn of slashActionListeners) {
    try {
      fn(event);
    } catch {
      /* ignore */
    }
  }
}

export const sessionEventListeners = new Set<SessionEventListener>();

/** Register a listener for session lifecycle events. Returns unsubscribe fn. */
export function onSessionEvent(listener: SessionEventListener): () => void {
  sessionEventListeners.add(listener);
  return () => {
    sessionEventListeners.delete(listener);
  };
}

export function emitSessionEvent(event: SessionEvent) {
  for (const fn of sessionEventListeners) {
    try {
      fn(event);
    } catch {
      /* ignore */
    }
  }
}

export const steerRestoreListeners = new Set<(event: SteerRestoreEvent) => void>();

export const sharedTurnBusyListeners = new Set<(event: SharedTurnBusyEvent) => void>();

export function onSharedTurnBusy(
  listener: (event: SharedTurnBusyEvent) => void,
): () => void {
  sharedTurnBusyListeners.add(listener);
  return () => {
    sharedTurnBusyListeners.delete(listener);
  };
}

export function emitSharedTurnBusy(event: SharedTurnBusyEvent): void {
  for (const listener of sharedTurnBusyListeners) {
    try {
      listener(event);
    } catch {
      /* ignore */
    }
  }
}

export function onSteerRestore(
  listener: (event: SteerRestoreEvent) => void,
): () => void {
  steerRestoreListeners.add(listener);
  return () => {
    steerRestoreListeners.delete(listener);
  };
}

export function emitSteerRestore(event: SteerRestoreEvent): void {
  if (event.applyToComposer === false) {
    for (const listener of steerRestoreListeners) {
      try {
        listener(event);
      } catch {
        /* ignore */
      }
    }
    return;
  }
  if (!event.text.trim() && !(event.attachments && event.attachments.length)) {
    return;
  }
  for (const listener of steerRestoreListeners) {
    try {
      listener(event);
    } catch {
      /* ignore */
    }
  }
}
