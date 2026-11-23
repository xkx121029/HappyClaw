/**
 * Turn boundaries: finalize/seal streaming speakers, turn duration, HITL cards and error bubbles.
 */

import { generateId } from "../../../utils/messageParser";
import { type SessionStreamState } from "./sseHelpers";
import { isChatStreamError } from "../../../utils/chatStreamError";
import {
  isRoomHostSpeaker,
  sameStreamingSpeaker,
} from "../utils/messageGrouping";
import {
  isAskHitl,
  normalizeHitlRequest,
  parseActionArgs,
} from "../../../api/types/hitl";
import { isPausedAskTool } from "../utils/pendingHitl";
import {
  clearAllLiveSpeakers,
  clearSpeakerLive,
  clearStreamingFlags,
  getOrCreate,
} from "./chatStoreState";
import { sessionHostAgentId } from "./chatStoreSocket";

export function speakerMatchesFinalize(
  messageSpeaker: string | undefined,
  incomingSpeaker: string | undefined,
  hostId?: string,
  teamRoom = false,
): boolean {
  if (!(incomingSpeaker || "").trim()) {
    return isRoomHostSpeaker(messageSpeaker, hostId);
  }
  return sameStreamingSpeaker(
    messageSpeaker,
    incomingSpeaker,
    hostId,
    teamRoom,
  );
}

/** Persist whether this session is a team host room (listen-only / ask_agent). */
export function setSessionTeamRoom(sessionId: string, isTeam: boolean): void {
  getOrCreate(sessionId).isTeamRoom = isTeam;
}

export /** Seal only the host wrap-up bubble so dispatch can keep streaming. */
function finalizeWrapupMessages(
  state: SessionStreamState,
  speaker?: string,
): void {
  const hostId = sessionHostAgentId(state);
  state.messages = state.messages.map((m) => {
    if (m.status !== "streaming" || !m.teamWrapup) return m;
    if (
      !sameStreamingSpeaker(
        m.speakerAgentId,
        speaker,
        hostId,
        Boolean(state.isTeamRoom),
      )
    )
      return m;
    return { ...m, status: "done" as const };
  });
}

export /** Seal the room host (stamped id, then unlabeled leftovers). Members stay live. */
function finalizeHostTurn(state: SessionStreamState, sessionId?: string): void {
  const hostId = sessionHostAgentId(state, sessionId);
  finalizeStreamingMessages(state, hostId, hostId);
  if (hostId) finalizeStreamingMessages(state, undefined, hostId);
}

export function stampTurnDuration(
  state: SessionStreamState,
  durationMs: number,
  speaker: string | undefined,
  sessionId?: string,
): void {
  if (!Number.isFinite(durationMs) || durationMs < 0) return;
  const hostId = sessionHostAgentId(state, sessionId);
  const rounded = Math.round(durationMs);
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    if (message.role !== "assistant" || message.toolData) continue;
    if (
      !speakerMatchesFinalize(
        message.speakerAgentId,
        speaker,
        hostId,
        Boolean(state.isTeamRoom),
      )
    ) {
      continue;
    }
    state.messages[index] = { ...message, durationMs: rounded };
    return;
  }
}

export /** Mark still-streaming assistant bubbles as done for one speaker (or host). */
function finalizeStreamingMessages(
  state: SessionStreamState,
  speaker?: string,
  hostAgentId?: string,
): void {
  const hostId = hostAgentId ?? sessionHostAgentId(state);
  state.messages = state.messages.map((m) => {
    if (m.status !== "streaming") return m;
    if (
      !speakerMatchesFinalize(
        m.speakerAgentId,
        speaker,
        hostId,
        Boolean(state.isTeamRoom),
      )
    )
      return m;
    // ModelRetryMiddleware may surface failures as assistant text instead of
    // type=error — promote those to an error bubble so users get guidance + retry.
    if (
      m.role === "assistant" &&
      !m.toolData &&
      typeof m.content === "string" &&
      isChatStreamError(m.content)
    ) {
      return {
        ...m,
        status: "error" as const,
        errorInfo: { code: "stream_error", source: "model_retry" },
      };
    }
    return { ...m, status: "done" as const };
  });
  if (state.runUsage && isRoomHostSpeaker(speaker, hostId)) {
    for (let index = state.messages.length - 1; index >= 0; index -= 1) {
      const message = state.messages[index];
      if (message.role !== "assistant" || message.toolData) continue;
      if (
        !speakerMatchesFinalize(
          message.speakerAgentId,
          speaker,
          hostId,
          Boolean(state.isTeamRoom),
        )
      )
        continue;
      state.messages[index] = { ...message, usage: { ...state.runUsage } };
      break;
    }
  }
  state.streamMsg = "";
  state.streamId = "";
  state.streamBlockType = "";
}

export function parseHitlRequest(raw: Record<string, unknown>) {
  const normalized = normalizeHitlRequest(raw);
  const requests = Array.isArray(normalized.action_requests)
    ? normalized.action_requests
    : [];
  const action_requests = requests
    .filter((item) => item && typeof item === "object")
    .map((item) => {
      const row = item as Record<string, unknown>;
      return {
        name: typeof row.name === "string" ? row.name : "tool",
        args: parseActionArgs(row.args),
        description:
          typeof row.description === "string" ? row.description : undefined,
      };
    });
  const review_configs = Array.isArray(normalized.review_configs)
    ? normalized.review_configs
        .filter((item) => item && typeof item === "object")
        .map(
          (item) =>
            item as {
              action_name: string;
              allowed_decisions: string[];
            },
        )
    : undefined;
  const pendingId =
    typeof normalized.pending_id === "string"
      ? normalized.pending_id
      : typeof raw.pending_id === "string"
      ? raw.pending_id
      : undefined;
  return {
    action_requests,
    review_configs,
    status: "pending" as const,
    ...(pendingId ? { pending_id: pendingId } : {}),
  };
}

export function resolveHitlPending(
  state: SessionStreamState,
  status: "approved" | "rejected",
  policy?: { mode: string; tools?: string[] },
  pendingId?: string,
): void {
  const resolution =
    status === "rejected"
      ? undefined
      : policy?.mode === "allow_all"
      ? "allow_all"
      : policy?.mode === "allow_tools"
      ? "allow_tool"
      : "approve";
  const targetId = pendingId?.trim();
  state.messages = state.messages.map((m) => {
    const hitl = m.hitlData;
    if (!hitl || (hitl.status ?? "pending") !== "pending") return m;
    if (targetId && hitl.pending_id !== targetId) return m;
    return { ...m, hitlData: { ...hitl, status, resolution } };
  });
}

export function pendingCardSpeaker(
  state: SessionStreamState,
  pendingId?: string,
): string | undefined {
  const targetId = pendingId?.trim();
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    const hitl = message?.hitlData;
    if (!hitl || (hitl.status ?? "pending") !== "pending") continue;
    if (targetId && hitl.pending_id !== targetId) continue;
    const speaker = message?.speakerAgentId?.trim();
    if (speaker) return speaker;
  }
  return undefined;
}

export function handleHitlRequired(
  state: SessionStreamState,
  request: Record<string, unknown>,
  speaker?: string,
): void {
  const memberPause = Boolean(state.isTeamRoom) && Boolean(speaker?.trim());
  if (memberPause) {
    finalizeStreamingMessages(state, speaker);
    clearSpeakerLive(state, speaker);
    if (state.liveSpeakers.size === 0) {
      clearStreamingFlags(state, { keepSteer: true });
    }
  } else {
    finalizeStreamingMessages(state);
    clearStreamingFlags(state, { keepSteer: true });
    clearAllLiveSpeakers(state);
  }
  const hitlData = parseHitlRequest(request);
  const askPause = isAskHitl(hitlData.action_requests);
  const existingIdx = [...state.messages]
    .map((message, index) => ({ message, index }))
    .reverse()
    .find(({ message }) => {
      const hitl = message.hitlData;
      if (hitlData.pending_id && hitl?.pending_id === hitlData.pending_id) {
        return true;
      }
      if (
        speaker &&
        message.speakerAgentId &&
        message.speakerAgentId !== speaker
      ) {
        return false;
      }
      if (askPause) {
        if (isPausedAskTool(message)) return true;
        return (
          Boolean(hitl) &&
          (hitl?.status ?? "pending") === "pending" &&
          isAskHitl(hitl?.action_requests) &&
          !hitl?.pending_id
        );
      }
      return (
        Boolean(hitl) &&
        (hitl?.status ?? "pending") === "pending" &&
        !isAskHitl(hitl?.action_requests)
      );
    })?.index;
  if (existingIdx !== undefined) {
    const current = state.messages[existingIdx];
    state.messages = [
      ...state.messages.slice(0, existingIdx),
      {
        ...current,
        hitlData: {
          ...current.hitlData,
          ...hitlData,
        },
        speakerAgentId: speaker ?? current.speakerAgentId,
        status: "done",
      },
      ...state.messages.slice(existingIdx + 1),
    ];
    return;
  }
  state.messages = [
    ...state.messages,
    {
      id: generateId(),
      role: "assistant",
      content: "",
      hitlData,
      status: "done",
      timestamp: Date.now(),
      ...(speaker ? { speakerAgentId: speaker } : {}),
    },
  ];
}

export /** Append an assistant error bubble — used for backend-emitted error
 *  chunks and HTTP-layer failures. */
function appendErrorBubble(
  state: SessionStreamState,
  message: string,
  errorCode?: string,
): void {
  state.messages = [
    ...state.messages,
    {
      id: generateId(),
      role: "assistant",
      content: message,
      errorInfo: {
        code: errorCode || "stream_error",
        source: "frontend_stream",
      },
      status: "error",
      timestamp: Date.now(),
    },
  ];
}
