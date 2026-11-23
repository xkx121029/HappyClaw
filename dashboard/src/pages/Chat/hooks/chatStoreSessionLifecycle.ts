/**
 * Session lifecycle and key migration: cancel, remove, detach and rename cached sessions.
 */

import {
  clearInflightTail,
  moveInflightTail,
} from "../utils/inflightTranscriptCache";
import {
  clearAllLiveSpeakers,
  clearStreamingFlags,
  sessionStates,
  usageSamplesByState,
} from "./chatStoreState";
import { cancelStreamPaint, notify } from "./chatStorePublish";
import {
  assignFocusedChatSession,
  getFocusedChatSession,
} from "./chatStoreFocus";
import {
  clearStreamActivity,
  clearStreamWatchdog,
  closeLiveSocket,
  liveSockets,
  pendingResumeBySession,
  postCancelTurn,
  sendCancelFrame,
  streamActivityAt,
  streamWatchdogs,
} from "./chatStoreSocket";

/** Cancel any in-flight stream for a session (user stop). */
export function cancelStream(
  sessionId: string,
  target?: { agentId?: string | null; threadId?: string | null },
) {
  const state = sessionStates.get(sessionId);
  const live = liveSockets.get(sessionId);
  if (live) {
    live.intentionalClose = true;
    live.userCancelled = true;
    sendCancelFrame(live.ws, live.threadId || sessionId);
  }
  // Always mirror Stop over HTTP: a parked/closed socket would otherwise leave
  // the server turn running (and a stale HITL park behind it).
  postCancelTurn(
    live?.agentId || target?.agentId || "",
    live?.threadId || target?.threadId || sessionId,
  );
  if (!state) return;
  const hadAbort = Boolean(state.abortController);
  const hadStreaming = state.isStreaming;
  const hadStreamingMsgs = state.messages.some((m) => m.status === "streaming");
  const hadLive = state.liveSpeakers.size > 0;
  state.abortController?.abort();
  state.abortController = null;
  clearStreamingFlags(state);
  clearAllLiveSpeakers(state);
  clearStreamActivity(sessionId);
  pendingResumeBySession.delete(sessionId);
  state.runUsage = null;
  usageSamplesByState.delete(state);
  if (hadStreamingMsgs) {
    state.messages = state.messages.map((m) =>
      m.status === "streaming" ? { ...m, status: "done" as const } : m,
    );
  }
  if (hadAbort || hadStreaming || hadStreamingMsgs || hadLive) {
    notify(state);
  }
}

/** Remove a session from the cache entirely. */
export function removeSession(sessionId: string) {
  const state = sessionStates.get(sessionId);
  if (state) {
    cancelStreamPaint(state);
    state.abortController?.abort();
    sessionStates.delete(sessionId);
  }
  pendingResumeBySession.delete(sessionId);
  clearStreamActivity(sessionId);
  clearStreamWatchdog(sessionId);
  clearInflightTail(sessionId);
  closeLiveSocket(sessionId, { intentional: true, userCancelled: true });
}

/** Drop a session map key without destroying the underlying state object.
 *
 * Used to break ``__pending__`` → real-thread aliases left by
 * :func:`renameSessionKey`. Without this, the next "New Chat" reuses
 * ``__pending__`` and mutates the previous thread's message bucket
 * (cross-thread stream bleed).
 */
export function detachSessionKey(sessionId: string): void {
  sessionStates.delete(sessionId);
}

/** Rename a cached session's key (e.g. temp id → real UUID).
 *
 * Migrates live sockets / resume bookkeeping to *newId*. The old key is
 * detached on a microtask so the current render can still read it, but a
 * later reuse of ``__pending__`` cannot share the same state object.
 */
export function renameSessionKey(oldId: string, newId: string) {
  const state = sessionStates.get(oldId);
  if (state && oldId !== newId) {
    sessionStates.set(newId, state);
    // Move live socket + resume bookkeeping to the canonical thread id so
    // loadHistory / attachThread for *newId* still see the open stream.
    const live = liveSockets.get(oldId);
    if (live) {
      liveSockets.delete(oldId);
      liveSockets.set(newId, live);
    }
    const pending = pendingResumeBySession.get(oldId);
    if (pending) {
      pendingResumeBySession.delete(oldId);
      pendingResumeBySession.set(newId, pending);
    }
    const activity = streamActivityAt.get(oldId);
    if (activity != null) {
      streamActivityAt.delete(oldId);
      streamActivityAt.set(newId, activity);
    }
    const wd = streamWatchdogs.get(oldId);
    if (wd != null) {
      streamWatchdogs.delete(oldId);
      streamWatchdogs.set(newId, wd);
    }
    if (getFocusedChatSession() === oldId) {
      assignFocusedChatSession(newId);
    }
    state.sessionKey = newId;
    moveInflightTail(oldId, newId);
    // Notify listeners so that components subscribed under the new key
    // (after a navigate) immediately see the existing messages.
    notify(state);
    // Detach the temporary key after the current turn so React can finish
    // reading the pending snapshot, but before the next New Chat reuses it.
    queueMicrotask(() => {
      if (
        sessionStates.get(oldId) === state &&
        sessionStates.get(newId) === state
      ) {
        sessionStates.delete(oldId);
      }
    });
  }
}

/**
 * Look up the store key that holds data for a given session ID.
 * Temporary ids are renamed to real thread ids via renameSessionKey; the
 * old key is detached shortly after, so callers should prefer the canonical
 * thread id from the URL.
 */
export function resolveSessionKey(sessionId: string): string {
  // Direct match — most common path
  if (sessionStates.has(sessionId)) return sessionId;
  return sessionId;
}

/** Debug: dump all session keys and their message counts (noop in production). */
export function debugDump() {
  // Intentionally silent in production
}
