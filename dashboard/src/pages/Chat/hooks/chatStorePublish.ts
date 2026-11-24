/**
 * Snapshot publication: subscribe, notify, the streaming paint timer and history read cursors.
 */

import { type SessionSnapshot, type SessionStreamState } from "./sseHelpers";
import { inFlightTail } from "../utils/mergeHistoryTail";
import {
  flushInflightTail,
  scheduleInflightTail,
} from "../utils/inflightTranscriptCache";
import {
  EMPTY_SNAPSHOT,
  buildSnapshot,
  getOrCreate,
  sessionStates,
} from "./chatStoreState";

export /**
 * Token / reasoning paints. A fast stream used to call React on every
 * fragment and starve in-flight fetches (expert profile, context usage).
 * The snapshot stays current immediately; listeners flush on this interval.
 */
const STREAM_PAINT_MS = 50;

export const streamPaintTimers = new Map<
  SessionStreamState,
  ReturnType<typeof setTimeout>
>();

export function cancelStreamPaint(state: SessionStreamState): void {
  const timer = streamPaintTimers.get(state);
  if (timer === undefined) return;
  clearTimeout(timer);
  streamPaintTimers.delete(state);
}

export function publish(state: SessionStreamState): void {
  for (const fn of state.listeners) {
    try {
      fn();
    } catch {
      /* ignore */
    }
  }
}

export function rememberInflight(state: SessionStreamState): void {
  const sessionId = state.sessionKey || "";
  if (!sessionId || sessionId.startsWith("__")) return;
  const live =
    state.isStreaming ||
    state.liveSpeakers.size > 0 ||
    state.messages.some((message) => message.status === "streaming");
  const tail = inFlightTail(state.messages);
  if (live) {
    scheduleInflightTail(sessionId, tail);
    return;
  }
  if (state.messages.some((m) => m.localPending)) {
    flushInflightTail(sessionId, tail);
  }
}

export function notify(state: SessionStreamState) {
  // Rebuild the snapshot reference so useSyncExternalStore sees the change.
  cancelStreamPaint(state);
  state._snapshot = buildSnapshot(state);
  rememberInflight(state);
  publish(state);
}

export /** Coalesce high-frequency stream fragments onto one paint. */
function notifyStreamingPaint(state: SessionStreamState): void {
  state._snapshot = buildSnapshot(state);
  rememberInflight(state);
  if (streamPaintTimers.has(state)) return;
  streamPaintTimers.set(
    state,
    setTimeout(() => {
      streamPaintTimers.delete(state);
      publish(state);
    }, STREAM_PAINT_MS),
  );
}

export function chunkPaintsImmediately(type: string): boolean {
  return (
    type !== "token" &&
    type !== "reasoning" &&
    type !== "usage" &&
    type !== "state_update" &&
    type !== "state_snapshot"
  );
}

// ── Public API ────────────────────────────────────────────────────────────

/** Subscribe to state changes for a session. Returns unsubscribe fn. */
export function subscribe(sessionId: string, listener: () => void): () => void {
  const state = getOrCreate(sessionId);
  state.listeners.add(listener);
  return () => {
    state.listeners.delete(listener);
  };
}

/** Capture the session revision before an asynchronous history read. */
export function beginHistoryRead(sessionId: string): number {
  return getOrCreate(sessionId).historyEpoch ?? 0;
}

export function isHistoryReadCurrent(
  sessionId: string,
  epoch: number,
): boolean {
  return sessionStates.get(sessionId)?.historyEpoch === epoch;
}

/** Get a read-only snapshot of the session state (referentially stable). */
export function getSnapshot(sessionId: string): SessionSnapshot {
  const state = sessionStates.get(sessionId);
  if (!state) return EMPTY_SNAPSHOT;
  return state._snapshot;
}
