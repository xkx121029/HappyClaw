/**
 * Attaching a session to its live socket, including focus switching and resume binding.
 */

import { type HarnessChunk } from "../../../utils/parseHarnessChunk";
import { turnStatusAction } from "./turnStatusGate";
import { frameBelongsToThread } from "./frameThread";
import { inFlightTail } from "../utils/mergeHistoryTail";
import { flushInflightTail } from "../utils/inflightTranscriptCache";
import {
  MAX_STREAM_RESUME_ATTEMPTS,
  shouldEmitStreamResumeNotice,
  shouldResumeStreamAfterClose,
} from "./wsResumeGate";
import type { LiveSocket } from "./chatStoreTypes";
import { emitStreamEvent } from "./chatStoreEvents";
import {
  clearStreamingFlags,
  getOrCreate,
  hasStreamingMessages,
  sealInFlightAssistantMessages,
  sessionStates,
  usageSamplesByState,
} from "./chatStoreState";
import { notify } from "./chatStorePublish";
import {
  assignFocusedChatSession,
  focusedChatSessionId,
  isSessionFocused,
} from "./chatStoreFocus";
import {
  clearLiveSocket,
  clearStreamActivity,
  clearStreamWatchdog,
  closeLiveSocket,
  hitlKeepsSocket,
  isLiveSocketOpen,
  keepRoomSocket,
  liveSockets,
  parkLiveSocketForHitl,
  pendingResumeBySession,
  rememberRoomAgent,
  sendCancelFrame,
  sessionHostAgentId,
  startSocketPing,
  touchStreamActivity,
  tryOpenDashboardWs,
} from "./chatStoreSocket";
import { finalizeHostTurn } from "./chatStoreTurns";
import {
  applyThreadTitleFrame,
  beginStream,
  handleHarnessChunk,
  isHostTurnTerminal,
} from "./chatStoreStream";
import {
  applyRemoteUserFrame,
  applySteerProtocolFrame,
} from "./chatStoreSteer";

/** Tell the store which chat thread the UI is currently showing. */
export function setFocusedChatSession(sessionId: string | null): void {
  const next = sessionId && sessionId !== "__empty__" ? sessionId : null;
  const prev = focusedChatSessionId;
  assignFocusedChatSession(next);
  if (prev && prev !== next) {
    const prevState = sessionStates.get(prev);
    if (
      prevState &&
      (prevState.isStreaming ||
        prevState.messages.some((message) => message.status === "streaming") ||
        prevState.messages.some((m) => m.localPending))
    ) {
      flushInflightTail(prev, inFlightTail(prevState.messages));
    }
    // Listen sockets stay open after a turn so late team replies can land.
    // Leaving the room drops that idle bind; an in-flight turn keeps resume.
    if (!prevState?.isStreaming) {
      closeLiveSocket(prev, { intentional: true });
    }
  }
  if (next && next !== prev) {
    void rebindFocusedSessionIfNeeded(next);
  }
}

export async function rebindFocusedSessionIfNeeded(sessionId: string): Promise<void> {
  const state = sessionStates.get(sessionId);
  if (!state?.isStreaming) return;
  if (isLiveSocketOpen(sessionId)) return;
  const liveMeta = pendingResumeBySession.get(sessionId);
  if (liveMeta) {
    pendingResumeBySession.delete(sessionId);
    void attachThread(
      sessionId,
      liveMeta.agentId,
      liveMeta.threadId,
      liveMeta.onStreamEnd,
      liveMeta.resumeAttempt,
      liveMeta.opts,
    );
    return;
  }
  // isStreaming sticky without pending meta — caller may still attach via loadHistory
}

// ── Live WebSocket (send + weak stream resume) ─────────────────────────────

/**
 * After history load (or reconnect): subscribe to *threadId* and continue an
 * in-flight turn when the server reports ``turn_status.active``.
 *
 * @param resumeAttempt Internal counter for auto-reconnect after drop (do not
 *   pass from call sites except recursive re-attach).
 */
export async function attachThread(
  sessionId: string,
  agentId: string,
  threadId: string,
  onStreamEnd?: () => void,
  resumeAttempt = 0,
  opts?: { afterUnexpectedDrop?: boolean },
): Promise<void> {
  if (!agentId || !threadId || threadId === "__empty__") return;

  const existing = liveSockets.get(sessionId);
  if (existing && !existing.listenOnly && isLiveSocketOpen(sessionId)) {
    // An in-flight user_turn owns this session — do not steal its socket.
    return;
  }
  if (
    existing &&
    existing.agentId === agentId &&
    existing.threadId === threadId &&
    isLiveSocketOpen(sessionId)
  ) {
    // Already bound — do not re-send subscribe (avoids turn_status churn).
    return;
  }

  if (existing) {
    // Rebind only — do not send cancel / do not seal streaming bubbles.
    closeLiveSocket(sessionId, { intentional: true });
  }

  const state = getOrCreate(sessionId);
  rememberRoomAgent(state, agentId);
  const ws = tryOpenDashboardWs(agentId);
  if (!ws) {
    if (state.isStreaming) {
      clearStreamingFlags(state);
      clearStreamActivity(sessionId);
      notify(state);
    }
    return;
  }

  const live: LiveSocket = {
    ws,
    agentId,
    threadId,
    intentionalClose: false,
    userCancelled: false,
    listenOnly: true,
  };
  liveSockets.set(sessionId, live);

  // Do not clobber an in-flight sendTurn controller unless we need cancel
  // affinity for this resume socket.
  const controller = new AbortController();
  const previousController = state.abortController;
  state.abortController = controller;

  let finished = false;
  const finish = (mode: "all" | "host" = "all") => {
    if (finished) return;
    finished = true;
    clearStreamingFlags(state);
    clearStreamActivity(sessionId);
    pendingResumeBySession.delete(sessionId);
    if (state.abortController === controller) {
      state.abortController = null;
    }
    state.streamMsg = "";
    state.streamId = "";
    state.streamBlockType = "";
    if (mode === "host") {
      finalizeHostTurn(state, sessionId);
    } else {
      sealInFlightAssistantMessages(state);
    }
    notify(state);
    emitStreamEvent({ kind: "streamEnd", sessionId });
    onStreamEnd?.();
  };

  await new Promise<void>((resolve) => {
    let opened = false;
    const settleOpen = () => {
      if (opened) return;
      opened = true;
      resolve();
    };

    const onAbort = () => {
      live.intentionalClose = true;
      live.userCancelled = true;
      sendCancelFrame(ws, threadId);
      try {
        ws.close();
      } catch {
        // ignore
      }
      finish();
    };
    controller.signal.addEventListener("abort", onAbort, { once: true });

    ws.onopen = () => {
      if (liveSockets.get(sessionId)?.ws !== ws) return;
      touchStreamActivity(sessionId);
      startSocketPing(live);
      try {
        ws.send(JSON.stringify({ type: "subscribe", thread_id: threadId }));
      } catch {
        // ignore
      }
      settleOpen();
    };

    ws.onmessage = (event) => {
      if (liveSockets.get(sessionId)?.ws !== ws) return;
      try {
        const data = JSON.parse(String(event.data)) as Record<string, unknown>;
        if (!data || typeof data !== "object") return;
        if (!frameBelongsToThread(data, live.threadId)) return;
        const frameTurnId = (data as { turn_id?: unknown }).turn_id;
        if (
          (data as { type?: unknown }).type === "turn.ended" &&
          typeof frameTurnId === "string" &&
          state.activeTurnId &&
          frameTurnId !== state.activeTurnId
        )
          return;
        if (applyThreadTitleFrame(data)) return;

        if (data.type === "turn_status") {
          if (turnStatusAction(Boolean(data.active)) === "expect_stream") {
            if (!state.isStreaming) {
              state.runUsage = null;
              usageSamplesByState.delete(state);
              beginStream(state, sessionId);
              notify(state);
              emitStreamEvent({ kind: "streamStart", sessionId });
            } else {
              touchStreamActivity(sessionId);
            }
            if (
              shouldEmitStreamResumeNotice({
                resumeAttempt:
                  opts?.afterUnexpectedDrop && resumeAttempt === 0
                    ? 1
                    : resumeAttempt,
                turnActive: true,
              })
            ) {
              emitStreamEvent({ kind: "streamResume", sessionId });
            }
          } else if (state.isStreaming) {
            // Host thread went idle — seal the host turn, but keep this
            // socket so late team / inbox replies still land in the room.
            finalizeHostTurn(state, sessionId);
            notify(state);
            if (!hasStreamingMessages(state)) {
              finish();
            }
          } else if (state.abortController === controller) {
            state.abortController = previousController;
          }
          return;
        }

        if (data.type === "pong") return;
        if (applySteerProtocolFrame(state, data, sessionId)) {
          notify(state);
          if (
            isHostTurnTerminal(
              data,
              sessionHostAgentId(state, sessionId),
              state.activeTurnId,
            )
          ) {
            if (hitlKeepsSocket(data)) {
              parkLiveSocketForHitl(data, state, sessionId, live);
            } else if (keepRoomSocket(state, agentId)) {
              live.listenOnly = true;
              finish("host");
            } else {
              finish("all");
              closeLiveSocket(sessionId, { intentional: true });
            }
          }
          return;
        }
        if (applyRemoteUserFrame(state, data)) {
          notify(state);
          return;
        }

        handleHarnessChunk(state, data as unknown as HarnessChunk, sessionId);
        if (
          isHostTurnTerminal(
            data,
            sessionHostAgentId(state, sessionId),
            state.activeTurnId,
          )
        ) {
          if (hitlKeepsSocket(data)) {
            parkLiveSocketForHitl(data, state, sessionId, live);
          } else if (keepRoomSocket(state, agentId)) {
            live.listenOnly = true;
            finish("host");
          } else {
            finish("all");
            closeLiveSocket(sessionId, { intentional: true });
          }
        }
      } catch {
        // ignore malformed frames
      }
    };

    ws.onerror = () => {
      settleOpen();
    };

    ws.onclose = () => {
      if (liveSockets.has(sessionId) && liveSockets.get(sessionId)?.ws !== ws) {
        settleOpen();
        return;
      }
      controller.signal.removeEventListener("abort", onAbort);
      const wasIntentional = live.intentionalClose;
      const userCancelled = live.userCancelled;
      const stillStreaming = state.isStreaming;
      clearLiveSocket(sessionId, ws);
      settleOpen();
      // Socket replaced by a newer live for this session without user cancel —
      // keep sticky isStreaming so thread switch / rebind does not seal bubbles.
      if (wasIntentional && !userCancelled && stillStreaming) {
        if (state.abortController === controller) {
          state.abortController = previousController;
        }
        if (isLiveSocketOpen(sessionId)) {
          return;
        }
        // No replacement yet (edge race) — leave streaming, allow focus rebind.
        if (!pendingResumeBySession.has(sessionId)) {
          pendingResumeBySession.set(sessionId, {
            agentId,
            threadId,
            onStreamEnd,
            resumeAttempt: resumeAttempt + 1,
            opts: opts ?? { afterUnexpectedDrop: true },
          });
        }
        return;
      }
      if (stillStreaming && !wasIntentional) {
        // Keep grace window for sticky-seal watchdog while re-attaching.
        touchStreamActivity(sessionId);
      }
      const focused = isSessionFocused(sessionId);
      if (
        shouldResumeStreamAfterClose({
          intentionalClose: wasIntentional,
          isStreaming: stillStreaming,
          threadId,
          attempt: resumeAttempt,
          maxAttempts: MAX_STREAM_RESUME_ATTEMPTS,
          sessionFocused: focused,
        })
      ) {
        setTimeout(() => {
          if (sessionStates.get(sessionId) !== state) return;
          void attachThread(
            sessionId,
            agentId,
            threadId,
            onStreamEnd,
            resumeAttempt + 1,
            opts,
          );
        }, 400);
      } else if (
        stillStreaming &&
        !wasIntentional &&
        !focused &&
        resumeAttempt < MAX_STREAM_RESUME_ATTEMPTS
      ) {
        // Background tab: remember rebind when the user returns.
        pendingResumeBySession.set(sessionId, {
          agentId,
          threadId,
          onStreamEnd,
          resumeAttempt: resumeAttempt + 1,
          opts,
        });
        clearStreamWatchdog(sessionId);
      } else if (!wasIntentional && stillStreaming) {
        // Exhausted retries or failed open — do not leave sticky isStreaming.
        finish();
      } else if (state.abortController === controller) {
        state.abortController = previousController;
      }
    };
  });
}
