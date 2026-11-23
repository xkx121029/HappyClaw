/**
 * Module-level chat store that survives React component unmount/remount cycles.
 *
 * Key idea: WebSocket streams and accumulated messages live *outside* React.
 * Components subscribe to updates and get the latest snapshot on mount.
 * When the user navigates away and comes back, the messages (including
 * any in-flight streaming content) are still available.
 *
 * The implementation lives in the sibling `chatStore*.ts` modules; this file
 * is the facade that keeps the original import surface intact.
 */

import { getApiUrl } from "../../../api/config";
import { getAuthToken } from "../../../api/request";
import { generateId } from "../../../utils/messageParser";
import {
  type ChatAttachment,
  type ChatMessage,
  type SessionStreamState,
} from "./sseHelpers";
import {
  parseHarnessChunk,
  type HarnessChunk,
} from "../../../utils/parseHarnessChunk";
import { buildUserMessageContent } from "../utils/chatAttachments";
import { hasPendingHitl } from "../utils/pendingHitl";
import { turnStatusAction } from "./turnStatusGate";
import { frameBelongsToThread } from "./frameThread";
import { inFlightTail } from "../utils/mergeHistoryTail";
import { clipThreadTitle } from "../utils/threadTitle";
import {
  clearInflightTail,
  flushInflightTail,
  moveInflightTail,
} from "../utils/inflightTranscriptCache";
import {
  MAX_STREAM_RESUME_ATTEMPTS,
  shouldEmitStreamResumeNotice,
  shouldResumeStreamAfterClose,
} from "./wsResumeGate";
import type { LiveSocket } from "./chatStoreTypes";
import {
  emitSessionEvent,
  emitSharedTurnBusy,
  emitSteerRestore,
  emitStreamEvent,
} from "./chatStoreEvents";
import {
  clearAllLiveSpeakers,
  clearStreamingFlags,
  getOrCreate,
  hasStreamingMessages,
  markSpeakerLive,
  sealInFlightAssistantMessages,
  sessionStates,
  usageSamplesByState,
} from "./chatStoreState";
import { cancelStreamPaint, notify } from "./chatStorePublish";
import {
  assignFocusedChatSession,
  focusedChatSessionId,
  getFocusedChatSession,
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
  postCancelTurn,
  rememberRoomAgent,
  sendCancelFrame,
  sessionHostAgentId,
  startSocketPing,
  streamActivityAt,
  streamWatchdogs,
  touchStreamActivity,
  tryOpenDashboardWs,
} from "./chatStoreSocket";
import {
  appendErrorBubble,
  finalizeHostTurn,
  pendingCardSpeaker,
  resolveHitlPending,
} from "./chatStoreTurns";
import {
  noteTurnOwner,
  noteTurnOwnerFromLatestUser,
  sealPriorStreamingAssistants,
} from "./chatStoreMessageBubbles";
import {
  applyThreadTitleFrame,
  beginStream,
  handleHarnessChunk,
  isHostTurnTerminal,
  settleGeneratedTitle,
} from "./chatStoreStream";

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

async function rebindFocusedSessionIfNeeded(sessionId: string): Promise<void> {
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

// ── Send a message via Dashboard WebSocket (/api/agents/{id}/chat/ws) ────────
async function sendTurnWebSocket(
  sessionId: string,
  agentId: string,
  sessionKey: string,
  text: string,
  messageContent: string | Array<Record<string, unknown>>,
  controller: AbortController,
  finish: (mode?: "all" | "host") => void,
  modelRef?: string | null,
  threadId?: string | null,
  mcpServers?: string[] | null,
  knowledgeBaseIds?: string[] | null,
  targetAgentIds?: string[] | null,
  onStreamEnd?: () => void,
  reasoningMode?: "auto" | "enabled" | "disabled",
  reasoningEffort?: string | null,
  conversationMode?: "ask" | "plan" | "craft" | null,
  hitlPolicy?: { mode: string; tools?: string[] } | null,
  clientMessageId?: string | null,
): Promise<boolean> {
  const state = getOrCreate(sessionId);
  const resolvedThreadId = (threadId || sessionId).trim();

  if (liveSockets.has(sessionId)) {
    // Replace prior socket for this session without cancelling the server turn.
    closeLiveSocket(sessionId, { intentional: true });
  }

  return new Promise((resolve) => {
    const ws = tryOpenDashboardWs(agentId);
    if (!ws) {
      resolve(false);
      return;
    }

    const live: LiveSocket = {
      ws,
      agentId,
      threadId: resolvedThreadId,
      intentionalClose: false,
      userCancelled: false,
      listenOnly: false,
    };
    liveSockets.set(sessionId, live);

    let settled = false;
    let sawTurnStarted = false;
    const settle = (ok: boolean) => {
      if (settled) return;
      settled = true;
      resolve(ok);
    };

    let openedForTurn = false;
    const onAbort = () => {
      live.intentionalClose = true;
      live.userCancelled = true;
      sendCancelFrame(ws, resolvedThreadId);
      try {
        ws.close();
      } catch {
        // ignore
      }
      finish();
      settle(true);
    };
    controller.signal.addEventListener("abort", onAbort, { once: true });

    ws.onopen = () => {
      if (liveSockets.get(sessionId)?.ws !== ws) return;
      openedForTurn = true;
      startSocketPing(live);
      const payload: Record<string, unknown> = {
        type: "user_turn",
        text: typeof messageContent === "string" ? messageContent : text,
        session_key: sessionKey,
        messages: [
          {
            role: "user",
            content: messageContent,
            ...(clientMessageId ? { id: clientMessageId } : {}),
          },
        ],
      };
      if (threadId) payload.thread_id = threadId;
      if (modelRef) payload.model = modelRef;
      // Always send the array (including []) so the server can honor Dashboard
      // opt-out of default_open connectors for this turn.
      if (mcpServers !== undefined && mcpServers !== null) {
        payload.mcp_servers = mcpServers;
      }
      // Always send the array (including []) so the server can honor Dashboard
      // opt-out of default_open knowledge bases for this turn.
      if (knowledgeBaseIds !== undefined && knowledgeBaseIds !== null) {
        payload.knowledge_base_ids = knowledgeBaseIds;
      }
      if (targetAgentIds && targetAgentIds.length > 0) {
        payload.target_agent_ids = targetAgentIds;
      }
      if (reasoningMode) payload.reasoning_mode = reasoningMode;
      if (reasoningEffort) payload.reasoning_effort = reasoningEffort;
      if (conversationMode) payload.conversation_mode = conversationMode;
      if (hitlPolicy) payload.hitl_policy = hitlPolicy;
      ws.send(JSON.stringify(payload));
    };

    ws.onmessage = (event) => {
      if (liveSockets.get(sessionId)?.ws !== ws) return;
      try {
        const data = JSON.parse(String(event.data)) as HarnessChunk;
        if (!data || typeof data !== "object") return;
        if (!frameBelongsToThread(data, live.threadId)) return;
        const frameType = String((data as { type?: unknown }).type || "");
        if (frameType === "turn.started" || frameType === "turn.resumed") {
          sawTurnStarted = true;
        }
        const frameTurnId = (data as { turn_id?: unknown }).turn_id;
        if (
          frameType === "turn.ended" &&
          typeof frameTurnId === "string" &&
          state.activeTurnId &&
          frameTurnId !== state.activeTurnId
        )
          return;
        if (applyThreadTitleFrame(data as unknown as Record<string, unknown>)) {
          return;
        }
        if ((data as { type?: string }).type === "turn_status") return;
        if (
          applySteerProtocolFrame(
            state,
            data as unknown as Record<string, unknown>,
            sessionId,
          )
        ) {
          notify(state);
          if (frameType === "turn.busy") {
            const busyId = String(
              (data as { message_id?: unknown }).message_id || "",
            ).trim();
            const rejectsThisSend =
              !sawTurnStarted ||
              (Boolean(clientMessageId) &&
                busyId === String(clientMessageId).trim());
            // The server refused this send. Drop the spinner we raised so
            // Stop cannot cancel the turn that is still running.
            if (rejectsThisSend) {
              live.listenOnly = true;
              controller.signal.removeEventListener("abort", onAbort);
              if (state.abortController === controller) {
                state.abortController = null;
              }
              state.isStreaming = false;
              state.thinkingStartedAt = null;
              clearStreamActivity(sessionId);
              notify(state);
              settle(true);
            }
            return;
          }
          if (
            isHostTurnTerminal(
              data,
              sessionHostAgentId(state, sessionId),
              state.activeTurnId,
            )
          ) {
            if (hitlKeepsSocket(data)) {
              parkLiveSocketForHitl(data, state, sessionId, live);
            } else {
              controller.signal.removeEventListener("abort", onAbort);
              if (keepRoomSocket(state, agentId)) {
                live.listenOnly = true;
                finish("host");
              } else {
                finish("all");
                closeLiveSocket(sessionId, { intentional: true });
              }
            }
            settle(true);
          }
          return;
        }
        if (
          applyRemoteUserFrame(
            state,
            data as unknown as Record<string, unknown>,
          )
        ) {
          notify(state);
          return;
        }
        handleHarnessChunk(state, data, sessionId);
        if (
          isHostTurnTerminal(
            data,
            sessionHostAgentId(state, sessionId),
            state.activeTurnId,
          )
        ) {
          if (hitlKeepsSocket(data)) {
            parkLiveSocketForHitl(data, state, sessionId, live);
          } else {
            controller.signal.removeEventListener("abort", onAbort);
            if (keepRoomSocket(state, agentId)) {
              live.listenOnly = true;
              finish("host");
            } else {
              finish("all");
              closeLiveSocket(sessionId, { intentional: true });
            }
          }
          settle(true);
        }
      } catch {
        // ignore malformed frames
      }
    };

    ws.onerror = () => {
      // Prefer onclose to decide resume vs fail — browsers almost always fire both.
    };

    ws.onclose = () => {
      if (liveSockets.has(sessionId) && liveSockets.get(sessionId)?.ws !== ws) {
        settle(true);
        return;
      }
      const wasIntentional = live.intentionalClose;
      const userCancelled = live.userCancelled;
      // Capture before any finish() clears streaming flags.
      const focused = isSessionFocused(sessionId);
      clearLiveSocket(sessionId, ws);
      controller.signal.removeEventListener("abort", onAbort);

      // Failed to open (unit tests / offline) — seal without resume thrash.
      if (!openedForTurn && !userCancelled) {
        if (!settled) {
          finish();
          settle(true);
        }
        return;
      }

      const shouldResume = shouldResumeStreamAfterClose({
        intentionalClose: wasIntentional,
        isStreaming: state.isStreaming,
        threadId: resolvedThreadId,
        sessionFocused: focused,
      });

      if (shouldResume) {
        // Keep isStreaming + partial assistant bubble; re-subscribe for later chunks.
        // Do NOT finish() — that seals incomplete content and blocks free-scroll UX.
        touchStreamActivity(sessionId);
        if (!settled) settle(true);
        setTimeout(() => {
          if (sessionStates.get(sessionId) !== state) return;
          void attachThread(
            sessionId,
            agentId,
            resolvedThreadId,
            onStreamEnd,
            0,
            {
              afterUnexpectedDrop: true,
            },
          );
        }, 400);
        return;
      }

      if (state.isStreaming && !wasIntentional && !focused) {
        touchStreamActivity(sessionId);
        pendingResumeBySession.set(sessionId, {
          agentId,
          threadId: resolvedThreadId,
          onStreamEnd,
          resumeAttempt: 1,
          opts: { afterUnexpectedDrop: true },
        });
        clearStreamWatchdog(sessionId);
        if (!settled) settle(true);
        return;
      }

      // Intentional socket *replace* (new live already bound) without user stop:
      // keep sticky isStreaming so rebind continues receiving chunks.
      if (wasIntentional && !userCancelled && state.isStreaming && !settled) {
        if (isLiveSocketOpen(sessionId)) {
          settle(true);
          return;
        }
      }

      if (!settled) {
        finish();
        settle(true);
      }

      // Host turn socket dropped after settle — re-subscribe so team members
      // can still stream into this room. 1:1 chats close after the host done.
      if (
        settled &&
        !wasIntentional &&
        !userCancelled &&
        keepRoomSocket(state, agentId) &&
        resolvedThreadId &&
        resolvedThreadId !== "__empty__" &&
        !isLiveSocketOpen(sessionId)
      ) {
        void attachThread(sessionId, agentId, resolvedThreadId, onStreamEnd);
      }
    };
  });
}

export async function sendTurn(
  sessionId: string,
  text: string,
  agentId: string,
  sessionKey: string,
  attachments?: ChatAttachment[],
  onStreamEnd?: () => void,
  modelRef?: string | null,
  threadId?: string | null,
  mcpServers?: string[] | null,
  knowledgeBaseIds?: string[] | null,
  targetAgentIds?: string[] | null,
  reasoningMode?: "auto" | "enabled" | "disabled",
  reasoningEffort?: string | null,
  conversationMode?: "ask" | "plan" | "craft" | null,
  hitlPolicy?: { mode: string; tools?: string[] } | null,
  clientMessageId?: string | null,
): Promise<void> {
  const state = getOrCreate(sessionId);
  rememberRoomAgent(state, agentId);

  if (sessionId === "__pending__" || threadId === "__pending__") {
    appendErrorBubble(
      state,
      "Thread is still being created. Please retry shortly.",
    );
    clearStreamingFlags(state);
    notify(state);
    onStreamEnd?.();
    return;
  }

  if (!agentId) {
    appendErrorBubble(state, "No agent selected. Pick one from the top bar.");
    clearStreamingFlags(state);
    clearStreamActivity(sessionId);
    notify(state);
    onStreamEnd?.();
    return;
  }

  // Replacing a listen-only (or already-finished) socket must not cancel
  // the host thread — a new user message should start a turn, not kill it.
  const priorLive = liveSockets.get(sessionId);
  if (priorLive?.listenOnly || !state.isStreaming) {
    closeLiveSocket(sessionId, { intentional: true });
    state.abortController = null;
  } else {
    state.abortController?.abort();
  }
  state.toolCallIdIndex = {};
  state.streamMsg = "";
  state.streamId = "";
  state.streamBlockType = "";
  const trimmed = text.trim();
  const userTurns = state.messages.filter(
    (message) => message.role === "user",
  ).length;
  if (userTurns === 1 && trimmed && !trimmed.startsWith("/")) {
    const title = clipThreadTitle(trimmed);
    if (title) {
      emitSessionEvent({
        kind: "sessionRenamed",
        sessionId,
        agentId,
        title,
        provisional: true,
      });
      settleGeneratedTitle(agentId, sessionId);
    }
  }
  beginStream(state, sessionId);
  state.runUsage = null;
  usageSamplesByState.delete(state);
  notify(state);

  emitStreamEvent({ kind: "streamStart", sessionId });

  const controller = new AbortController();
  state.abortController = controller;

  const messageContent = buildUserMessageContent(text, attachments);

  let finished = false;
  const finish = (mode: "all" | "host" = "all") => {
    if (finished) return;
    finished = true;
    clearStreamingFlags(state);
    clearStreamActivity(sessionId);
    pendingResumeBySession.delete(sessionId);
    state.abortController = null;
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

  const wsOk = await sendTurnWebSocket(
    sessionId,
    agentId,
    sessionKey,
    text,
    messageContent,
    controller,
    finish,
    modelRef,
    threadId,
    mcpServers,
    knowledgeBaseIds,
    targetAgentIds,
    onStreamEnd,
    reasoningMode,
    reasoningEffort,
    conversationMode,
    hitlPolicy,
    clientMessageId,
  );
  if (!wsOk) {
    state.messages = [
      ...state.messages,
      {
        id: generateId(),
        role: "assistant",
        content: "WebSocket connection failed. Check network or server logs.",
        errorInfo: { code: "ws_error", source: "frontend_stream" },
        status: "error",
        timestamp: Date.now(),
      },
    ];
    finish();
  }
}

async function consumeSseResponse(
  state: SessionStreamState,
  sessionId: string,
  res: Response,
  controller: AbortController,
  finish: (skipRefresh?: boolean, keepPaused?: boolean) => void,
): Promise<void> {
  const reader = res.body?.getReader();
  if (!reader) {
    finish();
    return;
  }

  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nlIdx: number;
    while ((nlIdx = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nlIdx).replace(/\r$/, "");
      buffer = buffer.slice(nlIdx + 1);
      if (!line) continue;
      const chunk = parseHarnessChunk(line);
      if (!chunk) continue;
      handleHarnessChunk(state, chunk, sessionId);
      if (chunk.type === "done" || chunk.type === "error") {
        controller.abort();
        const teamContinuing =
          chunk.type === "done" && chunk.team_member_continuing === true;
        const hitlPaused = chunk.type === "done" && chunk.hitl_paused === true;
        finish(teamContinuing || hitlPaused, hitlPaused);
        return;
      }
    }
  }

  if (buffer.length > 0) {
    const chunk = parseHarnessChunk(buffer);
    if (chunk) handleHarnessChunk(state, chunk, sessionId);
  }

  finish(false, hasPendingHitl(state.messages));
}

export async function resumeHitl(
  sessionId: string,
  agentId: string,
  threadId: string,
  decisions: Array<{ type: string; message?: string }>,
  onStreamEnd?: () => void,
  dismissed = false,
  hitlPolicy?: { mode: string; tools?: string[] },
  pendingId?: string,
): Promise<void> {
  const state = getOrCreate(sessionId);
  const live = liveSockets.get(sessionId);
  // The pause parks the dashboard socket as listen-only. Aborting it sends
  // cancel and streamEnd, which flushes messages the user queued during the
  // turn. Team rooms also keep that socket so the member answer can continue.
  const parkedListen =
    live?.listenOnly === true && live.ws.readyState === WebSocket.OPEN;
  const keepRoomListen = Boolean(state.isTeamRoom) && parkedListen;
  if (!parkedListen) {
    state.abortController?.abort();
  }
  const hitlStatus =
    dismissed || decisions.some((d) => d.type === "reject")
      ? "rejected"
      : "approved";
  const continuedSpeaker = keepRoomListen
    ? pendingCardSpeaker(state, pendingId)
    : undefined;
  resolveHitlPending(state, hitlStatus, hitlPolicy, pendingId);
  if (keepRoomListen) {
    // The member is still in this turn. Keep their bubble and the
    // "responding" indicator until their own done frame arrives.
    if (continuedSpeaker) markSpeakerLive(state, continuedSpeaker);
    notify(state);
  } else {
    beginStream(state, sessionId);
    notify(state);
    emitStreamEvent({ kind: "streamStart", sessionId });
  }

  const controller = new AbortController();
  state.abortController = controller;

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = getAuthToken();
  if (token) {
    (headers as Record<string, string>).Authorization = `Bearer ${token}`;
  }

  let finished = false;
  const finish = (skipRefresh = false, keepPaused = false) => {
    if (finished) return;
    finished = true;
    pendingResumeBySession.delete(sessionId);
    if (state.abortController === controller) {
      state.abortController = null;
    }
    if (skipRefresh && keepRoomListen && !keepPaused) {
      if (continuedSpeaker) markSpeakerLive(state, continuedSpeaker);
      notify(state);
      return;
    }
    if (keepPaused) {
      clearStreamingFlags(state, { keepSteer: true });
      clearStreamActivity(sessionId);
      state.streamMsg = "";
      state.streamId = "";
      state.streamBlockType = "";
      sealInFlightAssistantMessages(state);
      notify(state);
      return;
    }
    clearStreamingFlags(state);
    clearStreamActivity(sessionId);
    state.streamMsg = "";
    state.streamId = "";
    state.streamBlockType = "";
    sealInFlightAssistantMessages(state);
    notify(state);
    emitStreamEvent({ kind: "streamEnd", sessionId });
    // History reload now would replace the live member bubbles with a room
    // transcript that does not yet contain this answer.
    if (!skipRefresh) onStreamEnd?.();
  };

  try {
    const res = await fetch(getApiUrl(`/agents/${agentId}/chat/hitl/resume`), {
      method: "POST",
      headers,
      body: JSON.stringify({
        thread_id: threadId,
        decisions,
        ...(pendingId ? { pending_id: pendingId } : {}),
        ...(hitlPolicy ? { hitl_policy: hitlPolicy } : {}),
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      appendErrorBubble(state, `HITL resume failed (${res.status})`);
      finish();
      return;
    }
    await consumeSseResponse(state, sessionId, res, controller, finish);
  } catch (err: unknown) {
    if ((err as Error).name === "AbortError") return;
    appendErrorBubble(state, (err as Error).message || "HITL resume error");
    finish();
  }
}

function optimisticSteerMessageId(clientPendingId: string): string {
  return `steer:${clientPendingId}`;
}

function steerClientIds(
  data: Record<string, unknown>,
  state: SessionStreamState,
): string[] {
  const raw = data.client_pending_ids;
  if (Array.isArray(raw) && raw.length > 0) {
    return raw.map((id) => String(id || "").trim()).filter(Boolean);
  }
  return state.pendingSteers.map((s) => s.clientPendingId);
}

function optimisticAttachments(state: SessionStreamState): ChatAttachment[] {
  return state.messages.flatMap((message) =>
    message.id.startsWith("steer:") ? message.attachments ?? [] : [],
  );
}

function attachmentsFromSteerFrame(raw: unknown): ChatAttachment[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const attachments: ChatAttachment[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const workspacePath = String(row.workspace_path || "").trim();
    if (!workspacePath) continue;
    const kindRaw = String(row.kind || "file");
    const kind =
      kindRaw === "image" || kindRaw === "video" || kindRaw === "audio"
        ? kindRaw
        : "file";
    attachments.push({
      url: "",
      workspacePath,
      filename: String(row.filename || "") || undefined,
      mediaType: String(row.media_type || "") || undefined,
      kind,
    });
  }
  return attachments.length > 0 ? attachments : undefined;
}

/** Commit shows the user row in the transcript immediately. */
function appendOptimisticSteerMessage(
  state: SessionStreamState,
  clientPendingId: string,
  text: string,
  attachments?: ChatAttachment[],
): void {
  const id = optimisticSteerMessageId(clientPendingId);
  if (state.messages.some((m) => m.id === id)) return;
  state.messages = [
    ...state.messages,
    {
      id,
      role: "user",
      content: text,
      attachments:
        attachments && attachments.length > 0 ? attachments : undefined,
      steerPending: true,
      status: "done",
      timestamp: Date.now(),
    },
  ];
}

function findPendingSteer(
  state: SessionStreamState,
  data: Record<string, unknown>,
): SessionStreamState["pendingSteers"][number] | undefined {
  const cpid = String(data.client_pending_id || "").trim();
  const pendingId = String(data.pending_id || "").trim();
  return state.pendingSteers.find(
    (item) =>
      (cpid !== "" && item.clientPendingId === cpid) ||
      (pendingId !== "" && item.pendingId === pendingId),
  );
}

function restoreWithdrawnSteer(
  state: SessionStreamState,
  sessionId: string | undefined,
  pending: SessionStreamState["pendingSteers"][number],
): void {
  const optimistic = state.messages.find(
    (message) =>
      message.id === optimisticSteerMessageId(pending.clientPendingId),
  );
  emitSteerRestore({
    sessionId: sessionId || "",
    text: pending.text || optimistic?.content || "",
    attachments: pending.attachments || optimistic?.attachments,
    reason: "withdrawn",
  });
  dropOptimisticSteerMessages(state, [pending.clientPendingId]);
  state.pendingSteers = state.pendingSteers.filter(
    (item) => item.clientPendingId !== pending.clientPendingId,
  );
}

/**
 * Apply a remove result. ``fromBroadcast`` is the hub ``steer.removed`` frame;
 * the clicker's socket also gets ``steer.ack``. Already-drained steers stay
 * in the transcript because the continuation owns that text.
 */
function settleSteerRemoval(
  state: SessionStreamState,
  data: Record<string, unknown>,
  sessionId: string | undefined,
  fromBroadcast: boolean,
): void {
  const pending = findPendingSteer(state, data);
  if (!pending) return;
  if (data.already_drained === true) {
    state.pendingSteers = state.pendingSteers.map((item) =>
      item.clientPendingId === pending.clientPendingId
        ? { ...item, withdrawing: false }
        : item,
    );
    if (!fromBroadcast) {
      emitSteerRestore({
        sessionId: sessionId || "",
        text: "",
        reason: "already_drained",
        applyToComposer: false,
      });
    }
    return;
  }
  if (pending.withdrawing || !fromBroadcast) {
    restoreWithdrawnSteer(state, sessionId, pending);
    return;
  }
  dropOptimisticSteerMessages(state, [pending.clientPendingId]);
  state.pendingSteers = state.pendingSteers.filter(
    (item) => item.clientPendingId !== pending.clientPendingId,
  );
}

function rejectSteerWithdrawal(
  state: SessionStreamState,
  data: Record<string, unknown>,
  sessionId: string | undefined,
): void {
  const pending = findPendingSteer(state, data);
  if (!pending?.withdrawing) return;
  state.pendingSteers = state.pendingSteers.map((item) =>
    item.clientPendingId === pending.clientPendingId
      ? { ...item, withdrawing: false }
      : item,
  );
  emitSteerRestore({
    sessionId: sessionId || "",
    text: "",
    reason: String(data.reason || "rejected"),
    applyToComposer: false,
  });
}

/** Settle optimistic rows when their server fact arrives (drain/reject/end). */
function dropOptimisticSteerMessages(
  state: SessionStreamState,
  clientPendingIds: string[],
): void {
  const next = state.messages.filter(
    (m) => !clientPendingIds.some((c) => m.id === optimisticSteerMessageId(c)),
  );
  if (next.length !== state.messages.length) state.messages = next;
}

function authorFromFrame(raw: unknown): ChatMessage["author"] {
  if (!raw || typeof raw !== "object") return undefined;
  const row = raw as {
    user_id?: unknown;
    display_name?: unknown;
    username?: unknown;
    avatar_url?: unknown;
    avatar_icon?: unknown;
  };
  if (typeof row.user_id !== "number" || row.user_id <= 0) return undefined;
  return {
    userId: row.user_id,
    displayName: typeof row.display_name === "string" ? row.display_name : "",
    username: typeof row.username === "string" ? row.username : "",
    avatarUrl: typeof row.avatar_url === "string" ? row.avatar_url : null,
    avatarIcon: typeof row.avatar_icon === "string" ? row.avatar_icon : null,
  };
}

/** Show someone else's question as soon as their turn starts. */
function applyRemoteUserFrame(
  state: SessionStreamState,
  data: Record<string, unknown>,
): boolean {
  if (String(data.type || "") !== "user") return false;
  if ((data.meta as { steer?: boolean } | undefined)?.steer) return false;
  const author = authorFromFrame(data.author);
  if (author) noteTurnOwner(state, author.userId);
  const messageId = String(data.message_id || "").trim();
  if (!messageId) return false;
  if (state.messages.some((message) => message.id === messageId)) return true;
  const content = String(data.content || "");
  const attachments = attachmentsFromSteerFrame(data.attachments);
  if (!content && (!attachments || attachments.length === 0)) return true;
  state.messages = [
    ...state.messages,
    {
      id: messageId,
      role: "user",
      content,
      attachments,
      author,
      status: "done",
      timestamp: Date.now(),
    },
  ];
  return true;
}

function applySteerProtocolFrame(
  state: SessionStreamState,
  data: Record<string, unknown>,
  sessionId?: string,
): boolean {
  const type = String(data.type || "");
  if (type === "turn.busy") {
    const messageId = String(data.message_id || "").trim();
    if (messageId) {
      state.messages = state.messages.filter(
        (message) => message.id !== messageId,
      );
    }
    const clientPendingId = String(data.client_pending_id || "").trim();
    if (clientPendingId) {
      dropOptimisticSteerMessages(state, [clientPendingId]);
      state.pendingSteers = state.pendingSteers.filter(
        (item) => item.clientPendingId !== clientPendingId,
      );
    }
    emitSharedTurnBusy({
      sessionId: sessionId || "",
      messageId,
    });
    return true;
  }
  if (type === "turn.started" || type === "turn.resumed") {
    const turnId = String(data.turn_id || "").trim();
    if (type === "turn.started" && turnId) {
      const previous = (state.activeTurnId || "").trim();
      const foreignStream = state.messages.some(
        (message) =>
          message.role === "assistant" &&
          message.status === "streaming" &&
          message.turnId !== turnId,
      );
      if ((previous && previous !== turnId) || (!previous && foreignStream)) {
        sealPriorStreamingAssistants(state);
      }
    }
    if (turnId) state.activeTurnId = turnId;
    if (type === "turn.started") noteTurnOwnerFromLatestUser(state);
    // Idle commit becomes a normal turn. Keep the optimistic user row —
    // it is the live bubble until history returns the same text. Stop
    // tracking it so a later turn.ended does not delete it.
    if (type === "turn.started") {
      // This steer became a normal turn. Keep the row, but it is no longer
      // a queued correction that can be withdrawn.
      state.messages = state.messages.map((message) =>
        message.steerPending ? { ...message, steerPending: false } : message,
      );
      state.pendingSteers = [];
    }
    if (!state.isStreaming && sessionId) {
      beginStream(state, sessionId);
    }
    return true;
  }
  if (type === "turn.ended") {
    if (data.hitl_paused === true) {
      // Steers stay parked across the approval pause. Keep the turn id
      // so a committed row can still be withdrawn.
      return true;
    }
    state.activeTurnId = null;
    if (!state.isTeamRoom) state.activeTurnUserId = null;
    dropOptimisticSteerMessages(state, steerClientIds(data, state));
    state.pendingSteers = [];
    return true;
  }
  if (type === "steer.queue_snapshot") {
    const turnId = data.turn_id;
    state.activeTurnId =
      typeof turnId === "string" && turnId.trim() ? turnId.trim() : null;
    const items = Array.isArray(data.items) ? data.items : [];
    // Snapshot is the server-authoritative queue: keep optimistic rows for
    // items the server still knows, drop rows for the rest (settled or
    // ghosts from a dead socket), and preserve client-only full text.
    const snapshot = items
      .map((raw) => {
        if (!raw || typeof raw !== "object") return null;
        const item = raw as Record<string, unknown>;
        const clientPendingId = String(item.client_pending_id || "").trim();
        const pendingId = String(item.pending_id || "").trim();
        if (!clientPendingId || !pendingId) return null;
        const existing = state.pendingSteers.find(
          (s) => s.clientPendingId === clientPendingId,
        );
        return {
          clientPendingId,
          pendingId,
          preview: String(item.preview || "").trim() || existing?.preview || "",
          text: existing?.text,
          attachments: existing?.attachments,
          withdrawing: existing?.withdrawing,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x != null);
    dropOptimisticSteerMessages(
      state,
      state.pendingSteers
        .map((s) => s.clientPendingId)
        .filter((cpid) => !snapshot.some((s) => s.clientPendingId === cpid)),
    );
    state.pendingSteers = snapshot;
    return true;
  }
  if (type === "steer.queued") {
    const clientPendingId = String(data.client_pending_id || "").trim();
    const pendingId = String(data.pending_id || "").trim();
    if (!clientPendingId || !pendingId) return true;
    const preview = String(data.preview || "").trim();
    const existingIdx = state.pendingSteers.findIndex(
      (s) => s.pendingId === pendingId || s.clientPendingId === clientPendingId,
    );
    const existing = existingIdx >= 0 ? state.pendingSteers[existingIdx] : null;
    const next = {
      clientPendingId,
      pendingId,
      preview: preview || (existing?.preview ?? ""),
      // Full text is client-only (frames carry previews); keep what we sent.
      text: existing?.text,
      attachments: existing?.attachments,
      withdrawing: existing?.withdrawing,
    };
    if (existingIdx >= 0) {
      state.pendingSteers = state.pendingSteers.map((s, i) =>
        i === existingIdx ? next : s,
      );
    } else {
      state.pendingSteers = [...state.pendingSteers, next];
    }
    return true;
  }
  if (type === "steer.drained" || type === "steer.discarded") {
    // Drain swaps optimistic rows for the canonical server bubble (the
    // user/meta.steer frame lands first and already did the swap; this is
    // the safety net for reordered frames).
    dropOptimisticSteerMessages(state, steerClientIds(data, state));
    state.pendingSteers = [];
    return true;
  }
  if (type === "steer.removed") {
    settleSteerRemoval(state, data, sessionId, true);
    return true;
  }
  if (type === "steer.rejected") {
    const cpid = String(data.client_pending_id || "").trim();
    if (cpid) {
      const pending = state.pendingSteers.find(
        (s) => s.clientPendingId === cpid,
      );
      const optimistic = state.messages.find(
        (m) => m.id === optimisticSteerMessageId(cpid),
      );
      emitSteerRestore({
        sessionId: sessionId || "",
        text: pending?.text || optimistic?.content || "",
        attachments: pending?.attachments || optimistic?.attachments,
        reason: String(data.reason || "rejected"),
      });
      dropOptimisticSteerMessages(state, [cpid]);
      state.pendingSteers = state.pendingSteers.filter(
        (s) => s.clientPendingId !== cpid,
      );
    }
    return true;
  }
  if (type === "steer.ack") {
    const status = String(data.status || "");
    if (status === "removed") {
      settleSteerRemoval(state, data, sessionId, false);
    } else if (status === "rejected") {
      rejectSteerWithdrawal(state, data, sessionId);
    }
    return true;
  }
  if (
    type === "user" &&
    (data.meta as { steer?: boolean } | undefined)?.steer
  ) {
    // Server-synthesized user bubble for drained steers (meta.steer). The
    // drain is all-at-once, so settle every optimistic row here first —
    // the canonical coalesced bubble replaces them. Capture local preview
    // URLs before the rows go away.
    const keptAttachments = optimisticAttachments(state);
    dropOptimisticSteerMessages(state, [
      ...state.pendingSteers.map((s) => s.clientPendingId),
      ...state.messages
        .filter((m) => m.id.startsWith("steer:"))
        .map((m) => m.id.slice("steer:".length)),
    ]);
    state.pendingSteers = [];
    const content = String(data.content || "");
    const messageId = String(data.message_id || generateId());
    const frameAttachments = attachmentsFromSteerFrame(data.attachments);
    const attachments =
      keptAttachments.length > 0 ? keptAttachments : frameAttachments;
    if (
      (content || (attachments && attachments.length > 0)) &&
      !state.messages.some((m) => m.id === messageId)
    ) {
      state.messages = [
        ...state.messages,
        {
          id: messageId,
          role: "user",
          content,
          attachments,
          status: "done",
          timestamp: Date.now(),
        },
      ];
    }
    return true;
  }
  return false;
}

/** Send a mid-turn steer on the live socket (issue #1300).
 *
 * ``delivery:"auto"`` semantics: the send always goes out and the
 * SERVER decides (busy → steer queue, idle → normal new turn, stale
 * expected_turn_id → structured reject). The client never gates on its own
 * turn knowledge — a missing turnId just omits ``expected_turn_id`` and the
 * busy path binds to the live turn.
 */
/** Shared session: another person's turn is still running. */
export function sharedTurnBlocksSender(
  sessionId: string,
  userId: number | null | undefined,
  contributed: boolean,
): boolean {
  if (!contributed || userId == null || userId <= 0) return false;
  const state = sessionStates.get(sessionId);
  if (!state) return false;
  const teamStillTalking =
    Boolean(state.isTeamRoom) && state.liveSpeakers.size > 0;
  if (!state.isStreaming && !state.activeTurnId && !teamStillTalking)
    return false;
  const owner = state.activeTurnUserId;
  if (owner == null || owner <= 0) return false;
  return Number(owner) !== Number(userId);
}

export function sendSteerWhileBusy(
  sessionId: string,
  text: string,
  opts: {
    expectedTurnId?: string;
    clientPendingId?: string;
    attachments?: ChatAttachment[];
  },
): "ok" | "empty" | "no_socket" {
  const trimmed = text.trim();
  const attachments =
    opts.attachments && opts.attachments.length > 0
      ? opts.attachments
      : undefined;
  if (!trimmed && !attachments) return "empty";
  const live = liveSockets.get(sessionId);
  if (!live || live.ws.readyState !== WebSocket.OPEN) return "no_socket";
  const cpid = (opts.clientPendingId || generateId()).trim();
  const turnId = (opts.expectedTurnId || "").trim();
  const messageContent = buildUserMessageContent(trimmed, attachments);
  try {
    live.ws.send(
      JSON.stringify({
        type: "user_turn",
        text: trimmed,
        thread_id: live.threadId,
        delivery: "auto",
        ...(turnId ? { expected_turn_id: turnId } : {}),
        client_pending_id: cpid,
        messages: [{ role: "user", content: messageContent }],
      }),
    );
  } catch {
    return "no_socket";
  }
  // The committed input enters the visible conversation
  // immediately (optimistic user row), settled by steer.queued / drained /
  // rejected. The caller drops the chip on success; this entry tracks the
  // optimistic row until its server fact arrives.
  const state = getOrCreate(sessionId);
  appendOptimisticSteerMessage(state, cpid, trimmed, attachments);
  if (!state.pendingSteers.some((s) => s.clientPendingId === cpid)) {
    const previewSource = trimmed || attachments?.[0]?.filename || "";
    state.pendingSteers = [
      ...state.pendingSteers,
      {
        clientPendingId: cpid,
        pendingId: cpid,
        preview:
          previewSource.length > 200
            ? `${previewSource.slice(0, 199)}…`
            : previewSource,
        text: trimmed,
        attachments,
      },
    ];
    notify(state);
  }
  return "ok";
}

export function withdrawCommittedSteer(
  sessionId: string,
  messageId: string,
): "ok" | "pending_ack" | "missing" {
  const cpid = messageId.startsWith("steer:")
    ? messageId.slice("steer:".length)
    : "";
  if (!cpid) return "missing";
  const state = getOrCreate(sessionId);
  const pending = state.pendingSteers.find((s) => s.clientPendingId === cpid);
  if (!pending) return "missing";
  if (!state.activeTurnId || pending.pendingId === pending.clientPendingId) {
    return "pending_ack";
  }
  const live = liveSockets.get(sessionId);
  if (!live || live.ws.readyState !== WebSocket.OPEN) return "pending_ack";
  state.pendingSteers = state.pendingSteers.map((item) =>
    item.clientPendingId === cpid ? { ...item, withdrawing: true } : item,
  );
  notify(state);
  try {
    live.ws.send(
      JSON.stringify({
        type: "steer_remove",
        thread_id: live.threadId,
        turn_id: state.activeTurnId,
        client_pending_id: cpid,
        pending_id: pending.pendingId,
      }),
    );
  } catch {
    state.pendingSteers = state.pendingSteers.map((item) =>
      item.clientPendingId === cpid ? { ...item, withdrawing: false } : item,
    );
    notify(state);
    return "pending_ack";
  }
  return "ok";
}

export function getActiveTurnId(sessionId: string): string | null {
  return getOrCreate(sessionId).activeTurnId ?? null;
}

export type {
  ChatAttachment,
  ChatMessage,
  HitlActionRequest,
  HitlRequestData,
  SessionSnapshot,
  SessionStreamState,
  ToolCallData,
  UserComposerContext,
} from "./sseHelpers";

export type { ToolEventKind, ToolEvent, StreamEventKind, StreamEvent, SlashActionEvent, SessionEventKind, SessionEvent, SteerRestoreEvent, SharedTurnBusyEvent } from "./chatStoreTypes";
export { onToolEvent, emitToolEvent, onStreamEvent, onSlashAction, onSessionEvent, emitSessionEvent, onSteerRestore, onSharedTurnBusy } from "./chatStoreEvents";
export { subscribe, getSnapshot, beginHistoryRead, isHistoryReadCurrent } from "./chatStorePublish";
export { setPendingPlanPath, setMessages, setHistoryPage, restoreInflightTail, invalidateHistory, isHistoryStale, prependHistoryMessages, setHistoryLoadingMore, appendUserMessage, truncateAndReplaceUserMessage, appendPushMessage, clearMessages } from "./chatStoreHistory";
export { getFocusedChatSession, setPendingPrefillText, consumePendingPrefillText, setPendingPrefillAttachments, consumePendingPrefillAttachments } from "./chatStoreFocus";
export { hasLiveSocket } from "./chatStoreSocket";
export { setSessionTeamRoom } from "./chatStoreTurns";
export { patchToolResultData } from "./chatStoreToolCalls";
export { ingestHarnessChunk } from "./chatStoreStream";
