/**
 * Starting turns: the dashboard WebSocket send path, HTTP fallback and HITL resume.
 */

import { getApiUrl } from "../../../api/config";
import { getAuthToken } from "../../../api/request";
import { generateId } from "../../../utils/messageParser";
import { type ChatAttachment, type SessionStreamState } from "./sseHelpers";
import {
  parseHarnessChunk,
  type HarnessChunk,
} from "../../../utils/parseHarnessChunk";
import { buildUserMessageContent } from "../utils/chatAttachments";
import { hasPendingHitl } from "../utils/pendingHitl";
import { frameBelongsToThread } from "./frameThread";
import { clipThreadTitle } from "../utils/threadTitle";
import { shouldResumeStreamAfterClose } from "./wsResumeGate";
import type { LiveSocket } from "./chatStoreTypes";
import { emitSessionEvent, emitStreamEvent } from "./chatStoreEvents";
import {
  clearStreamingFlags,
  getOrCreate,
  markSpeakerLive,
  sealInFlightAssistantMessages,
  sessionStates,
  usageSamplesByState,
} from "./chatStoreState";
import { notify } from "./chatStorePublish";
import { isSessionFocused } from "./chatStoreFocus";
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
import {
  appendErrorBubble,
  finalizeHostTurn,
  pendingCardSpeaker,
  resolveHitlPending,
} from "./chatStoreTurns";
import {
  applyThreadTitleFrame,
  beginStream,
  handleHarnessChunk,
  isHostTurnTerminal,
  settleGeneratedTitle,
} from "./chatStoreStream";
import {
  applyRemoteUserFrame,
  applySteerProtocolFrame,
} from "./chatStoreSteer";
import { attachThread } from "./chatStoreAttach";

export // ── Send a message via Dashboard WebSocket (/api/agents/{id}/chat/ws) ────────
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

export async function consumeSseResponse(
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
