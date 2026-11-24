/**
 * Live dashboard WebSocket bookkeeping: socket registry, ping keepalive, stream watchdogs, room-host resolution and stop helpers.
 */

import { getApiUrl } from "../../../api/config";
import { getAuthToken } from "../../../api/request";
import { buildDashboardChatWsUrl } from "../../../api/modules/wsChat";
import { type SessionStreamState } from "./sseHelpers";
import {
  STREAM_STALE_WITHOUT_SOCKET_MS,
  shouldForceSealStream,
} from "./wsResumeGate";
import type { LiveSocket } from "./chatStoreTypes";
import { emitStreamEvent } from "./chatStoreEvents";
import {
  clearStreamingFlags,
  sealInFlightAssistantMessages,
  sessionStates,
} from "./chatStoreState";
import { notify } from "./chatStorePublish";
import { isSessionFocused } from "./chatStoreFocus";

export /** Sessions that dropped while unfocused; re-attach when the tab is shown again. */
const pendingResumeBySession = new Map<
  string,
  {
    agentId: string;
    threadId: string;
    onStreamEnd?: () => void;
    resumeAttempt: number;
    opts?: { afterUnexpectedDrop?: boolean };
  }
>();

export /** Try to open the dashboard chat WebSocket; null if construction fails. */
function tryOpenDashboardWs(agentId: string): WebSocket | null {
  try {
    return new WebSocket(buildDashboardChatWsUrl(agentId));
  } catch {
    return null;
  }
}

export // ── Live WebSocket bookkeeping (used by cancel / attach / send) ────────────

const CHAT_WS_PING_MS = 25_000;

export function startSocketPing(live: LiveSocket): void {
  if (live.pingTimer != null) return;
  live.pingTimer = setInterval(() => {
    if (live.ws.readyState !== WebSocket.OPEN) return;
    try {
      live.ws.send(JSON.stringify({ type: "ping" }));
    } catch {
      // ignore
    }
  }, CHAT_WS_PING_MS);
}

export function stopSocketPing(live: LiveSocket): void {
  if (live.pingTimer == null) return;
  clearInterval(live.pingTimer);
  live.pingTimer = undefined;
}

export const liveSockets = new Map<string, LiveSocket>();

export /** Last stream-related activity (chunk / open / status) for sticky seals. */
const streamActivityAt = new Map<string, number>();

export const streamWatchdogs = new Map<string, ReturnType<typeof setTimeout>>();

export function isLiveSocketOpen(sessionId: string): boolean {
  const live = liveSockets.get(sessionId);
  if (!live) return false;
  return (
    live.ws.readyState === WebSocket.OPEN ||
    live.ws.readyState === WebSocket.CONNECTING
  );
}

/** True when this session currently owns an open/connecting chat WebSocket. */
export function hasLiveSocket(sessionId: string): boolean {
  if (isLiveSocketOpen(sessionId)) return true;
  if (!sessionId || sessionId === "__empty__" || sessionId === "__default__") {
    return false;
  }
  for (const [key, live] of liveSockets) {
    if (live.threadId === sessionId && isLiveSocketOpen(key)) return true;
  }
  return false;
}

export function clearStreamWatchdog(sessionId: string): void {
  const timer = streamWatchdogs.get(sessionId);
  if (timer !== undefined) {
    clearTimeout(timer);
    streamWatchdogs.delete(sessionId);
  }
}

export function touchStreamActivity(sessionId: string): void {
  streamActivityAt.set(sessionId, Date.now());
  armStreamWatchdog(sessionId);
}

export function clearStreamActivity(sessionId: string): void {
  clearStreamWatchdog(sessionId);
  streamActivityAt.delete(sessionId);
}

export /**
 * If isStreaming sticks without a live socket past the grace window, seal so
 * overscroll-refresh / free-scroll UX recover. Open sockets (long tools) skip.
 */
function armStreamWatchdog(sessionId: string): void {
  clearStreamWatchdog(sessionId);
  streamWatchdogs.set(
    sessionId,
    setTimeout(() => {
      streamWatchdogs.delete(sessionId);
      const state = sessionStates.get(sessionId);
      if (!state) return;
      if (
        !shouldForceSealStream({
          isStreaming: state.isStreaming,
          hasLiveSocket: isLiveSocketOpen(sessionId),
          lastActivityAt: streamActivityAt.get(sessionId) ?? null,
          now: Date.now(),
          staleWithoutSocketMs: STREAM_STALE_WITHOUT_SOCKET_MS,
          sessionFocused: isSessionFocused(sessionId),
        })
      ) {
        // Still streaming with a socket, within grace, or unfocused — re-check later.
        if (state.isStreaming && isSessionFocused(sessionId)) {
          armStreamWatchdog(sessionId);
        }
        return;
      }
      // Seal sticky stream without cancelling a server turn (no socket).
      clearStreamingFlags(state);
      state.streamMsg = "";
      state.streamId = "";
      state.streamBlockType = "";
      sealInFlightAssistantMessages(state);
      clearStreamActivity(sessionId);
      notify(state);
      emitStreamEvent({ kind: "streamEnd", sessionId });
    }, STREAM_STALE_WITHOUT_SOCKET_MS),
  );
}

export function clearLiveSocket(sessionId: string, ws?: WebSocket): void {
  const live = liveSockets.get(sessionId);
  if (!live) return;
  if (ws && live.ws !== ws) return;
  stopSocketPing(live);
  liveSockets.delete(sessionId);
}

export function sendCancelFrame(ws: WebSocket, threadId: string): void {
  if (ws.readyState !== WebSocket.OPEN) return;
  try {
    ws.send(JSON.stringify({ type: "cancel", thread_id: threadId }));
  } catch {
    // ignore
  }
}

export /**
 * Stop over HTTP as well as over the socket.
 *
 * The WS `cancel` frame only reaches the turn while *this* page still holds a
 * subscribed socket. After a reload, an approval park, or when the turn was
 * started from another surface, sending it is a no-op and the server keeps
 * running — the UI then looks like Stop did nothing. This POST always lands.
 */
function postCancelTurn(agentId: string, threadId: string): void {
  if (!agentId || !threadId || threadId === "__empty__") return;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  void fetch(
    getApiUrl(
      `/agents/${encodeURIComponent(agentId)}/threads/${encodeURIComponent(
        threadId,
      )}/cancel`,
    ),
    { method: "POST", headers, keepalive: true },
  ).catch(() => {
    // Stop is best-effort: the local turn is already sealed.
  });
}

export function closeLiveSocket(
  sessionId: string,
  opts: { intentional: boolean; userCancelled?: boolean },
): void {
  const live = liveSockets.get(sessionId);
  if (!live) return;
  live.intentionalClose = opts.intentional;
  if (opts.userCancelled) {
    live.userCancelled = true;
  }
  try {
    live.ws.close();
  } catch {
    // ignore
  }
  clearLiveSocket(sessionId, live.ws);
}

export /** Keep the dashboard socket after host ``turn.ended``.
 *
 * Team rooms need it for member replies. Bridge rooms need it even when the
 * shadow agent is not flagged ``kind: team``, because closing the socket
 * unlistens the peer before members flush.
 */
function keepRoomSocket(
  state: SessionStreamState,
  agentId?: string | null,
): boolean {
  if (state.isTeamRoom) return true;
  return Boolean(agentId?.startsWith("bridge:"));
}

export function sessionHostAgentId(
  state: SessionStreamState,
  sessionId?: string,
): string | undefined {
  const fromState = state.roomAgentId?.trim();
  if (fromState) return fromState;
  if (!sessionId) return undefined;
  const fromSocket = liveSockets.get(sessionId)?.agentId?.trim();
  return fromSocket || undefined;
}

export function rememberRoomAgent(
  state: SessionStreamState,
  agentId?: string | null,
): void {
  const id = agentId?.trim();
  if (id) state.roomAgentId = id;
}

export function hitlKeepsSocket(data: {
  type?: unknown;
  hitl_paused?: unknown;
}): boolean {
  if (data.type === "hitl_required") return true;
  return data.type === "turn.ended" && data.hitl_paused === true;
}

export /** Unlock the composer and keep the socket subscribed across an approval pause. */
function parkLiveSocketForHitl(
  data: { type?: unknown; hitl_paused?: unknown },
  state: SessionStreamState,
  sessionId: string,
  live: LiveSocket,
): void {
  live.listenOnly = true;
  if (data.type !== "hitl_required") return;
  notify(state);
  emitStreamEvent({ kind: "streamEnd", sessionId });
}
