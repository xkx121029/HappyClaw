/**
 * Harness frame ingestion: thread titles, context/usage accounting, decisions and stream lifecycle.
 */

import type { TokenUsage } from "../../../api/types";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import { rewritePeerSpeakerId } from "../../../utils/remoteExpert";
import { generateId } from "../../../utils/messageParser";
import { parseDecisionNotice, type SessionStreamState } from "./sseHelpers";
import {
  streamSpeakerId,
  type HarnessChunk,
  type UsageChunk,
} from "../../../utils/parseHarnessChunk";
import {
  findSpeakerTextToContinue,
  sameStreamingSpeaker,
} from "../utils/messageGrouping";
import { emitSessionEvent, emitSlashAction } from "./chatStoreEvents";
import {
  clearAllLiveSpeakers,
  clearSpeakerLive,
  clearStreamingFlags,
  getOrCreate,
  hasStreamingMessages,
  markSpeakerLive,
  pruneIdleLiveSpeakers,
  usageSamplesByState,
} from "./chatStoreState";
import {
  chunkPaintsImmediately,
  notify,
  notifyStreamingPaint,
} from "./chatStorePublish";
import {
  clearStreamActivity,
  rememberRoomAgent,
  sessionHostAgentId,
  touchStreamActivity,
} from "./chatStoreSocket";
import {
  appendErrorBubble,
  finalizeStreamingMessages,
  finalizeWrapupMessages,
  handleHitlRequired,
  stampTurnDuration,
} from "./chatStoreTurns";
import {
  appendStreamingReasoning,
  appendStreamingToken,
  chunkTurnId,
  continueTokenOpts,
  findWrapupTextToContinue,
} from "./chatStoreMessageBubbles";
import { closeToolCall, upsertToolCall } from "./chatStoreToolCalls";

export function applyThreadTitleFrame(data: Record<string, unknown>): boolean {
  if (data.type !== "thread_title") return false;
  const title = typeof data.title === "string" ? data.title.trim() : "";
  const threadId =
    typeof data.thread_id === "string" ? data.thread_id.trim() : "";
  const agentId = typeof data.agent_id === "string" ? data.agent_id.trim() : "";
  if (title && threadId) {
    emitSessionEvent({
      kind: "sessionRenamed",
      sessionId: threadId,
      title,
      ...(agentId ? { agentId } : {}),
    });
  }
  return true;
}

export const TITLE_SETTLE_DELAYS_MS = [1000, 2000, 4000, 8000];

export /** Read the stored title after the socket that carried the turn has closed. */
function settleGeneratedTitle(agentId: string, threadId: string): void {
  if (!agentId || !threadId || threadId.startsWith("__")) return;
  void (async () => {
    for (const delay of TITLE_SETTLE_DELAYS_MS) {
      await new Promise((resolve) => setTimeout(resolve, delay));
      try {
        const rows = await octopThreadsApi.list(agentId, 50);
        const title = rows
          .find((row) => row.thread_id === threadId)
          ?.title?.trim();
        if (!title) continue;
        emitSessionEvent({
          kind: "sessionRenamed",
          sessionId: threadId,
          agentId,
          title,
        });
        return;
      } catch {
        // The next attempt still covers a title that lands after this miss.
      }
    }
  })();
}

export function beginStream(state: SessionStreamState, sessionId: string): void {
  clearAllLiveSpeakers(state);
  state.thinkingStartedAt = Date.now();
  state.isStreaming = true;
  touchStreamActivity(sessionId);
}

export // ── Harness chunk → state transitions ─────────────────────────────────────

function updateContextUsageFromChunk(
  state: SessionStreamState,
  chunk: { data: unknown },
): void {
  const data = chunk.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return;
  const messages = (data as { messages?: unknown[] }).messages;
  if (!Array.isArray(messages) || messages.length === 0) return;

  const last = messages[messages.length - 1] as Record<string, unknown>;
  const usageMeta = last.usage_metadata;
  if (!usageMeta || typeof usageMeta !== "object" || Array.isArray(usageMeta))
    return;

  const meta = usageMeta as Record<string, unknown>;
  const input =
    typeof meta.input_tokens === "number"
      ? meta.input_tokens
      : typeof meta.prompt_tokens === "number"
      ? meta.prompt_tokens
      : null;
  if (input !== null && input > 0) {
    state.contextUsage = { input_tokens: input };
  }
  attachDecisionSaved(state, messages);
}

export function decisionSavedOnMessage(message: Record<string, unknown>): number {
  const kwargs = message.additional_kwargs;
  if (!kwargs || typeof kwargs !== "object" || Array.isArray(kwargs)) return 0;
  const ctx = (kwargs as Record<string, unknown>).context_usage;
  if (!ctx || typeof ctx !== "object" || Array.isArray(ctx)) return 0;
  return usageCount((ctx as Record<string, unknown>).decision_saved);
}

export function attachDecisionSaved(
  state: SessionStreamState,
  messages: unknown[],
): void {
  const samples = usageSamplesByState.get(state);
  if (!samples) return;
  let changed = false;
  for (const item of messages) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const message = item as Record<string, unknown>;
    const saved = decisionSavedOnMessage(message);
    const id = typeof message.id === "string" ? message.id : "";
    if (saved <= 0 || !id || !samples.has(id)) continue;
    const current = samples.get(id);
    if (!current || usageCount(current.decision_saved) === saved) continue;
    samples.set(id, { ...current, decision_saved: saved });
    changed = true;
  }
  if (!changed || !state.runUsage) return;
  let total = 0;
  for (const sample of samples.values()) {
    total += usageCount(sample.decision_saved);
  }
  state.runUsage = { ...state.runUsage, decision_saved: total };
}

export function usageCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : 0;
}

export function applyUsageChunk(state: SessionStreamState, chunk: UsageChunk): void {
  if (chunk.call_id) {
    let samples = usageSamplesByState.get(state);
    if (!samples) {
      samples = new Map();
      usageSamplesByState.set(state, samples);
    }
    const previousSample = samples.get(chunk.call_id);
    samples.set(chunk.call_id, {
      ...chunk.usage,
      decision_saved:
        usageCount(chunk.usage.decision_saved) ||
        usageCount(previousSample?.decision_saved),
    });
    const latestInput = usageCount(chunk.usage.input_tokens);
    state.runUsage = Array.from(samples.values()).reduce<TokenUsage>(
      (total, usage) => {
        const input = usageCount(usage.input_tokens);
        const output = usageCount(usage.output_tokens);
        return {
          input_tokens: usageCount(total.input_tokens) + input,
          uncached_input_tokens:
            usageCount(total.uncached_input_tokens) +
            usageCount(usage.uncached_input_tokens),
          cache_read_tokens:
            usageCount(total.cache_read_tokens) +
            usageCount(usage.cache_read_tokens),
          cache_write_tokens:
            usageCount(total.cache_write_tokens) +
            usageCount(usage.cache_write_tokens),
          output_tokens: usageCount(total.output_tokens) + output,
          reasoning_tokens:
            usageCount(total.reasoning_tokens) +
            usageCount(usage.reasoning_tokens),
          total_tokens:
            usageCount(total.total_tokens) +
            usageCount(usage.total_tokens || input + output),
          model_calls: usageCount(total.model_calls) + 1,
          decision_saved:
            usageCount(total.decision_saved) + usageCount(usage.decision_saved),
          last_input_tokens: latestInput,
        };
      },
      {},
    );
    state.contextUsage = { input_tokens: latestInput };
    return;
  }

  const usage = chunk.usage;
  const input = usageCount(usage.input_tokens);
  const output = usageCount(usage.output_tokens);
  const previous = state.runUsage ?? {};
  state.runUsage = {
    input_tokens: usageCount(previous.input_tokens) + input,
    uncached_input_tokens:
      usageCount(previous.uncached_input_tokens) +
      usageCount(usage.uncached_input_tokens),
    cache_read_tokens:
      usageCount(previous.cache_read_tokens) +
      usageCount(usage.cache_read_tokens),
    cache_write_tokens:
      usageCount(previous.cache_write_tokens) +
      usageCount(usage.cache_write_tokens),
    output_tokens: usageCount(previous.output_tokens) + output,
    reasoning_tokens:
      usageCount(previous.reasoning_tokens) +
      usageCount(usage.reasoning_tokens),
    total_tokens:
      usageCount(previous.total_tokens) +
      usageCount(usage.total_tokens || input + output),
    model_calls: usageCount(previous.model_calls) + 1,
    decision_saved:
      usageCount(previous.decision_saved) + usageCount(usage.decision_saved),
    last_input_tokens: input,
  };
  state.contextUsage = { input_tokens: input };
}

export function chunkSpeakerId(
  chunk: { agent_id?: unknown } | object,
  hostAgentId?: string,
): string | undefined {
  return rewritePeerSpeakerId(hostAgentId, streamSpeakerId(chunk));
}

export function isHostTurnTerminal(
  data: {
    type?: unknown;
    agent_id?: unknown;
  },
  hostAgentId?: string,
  activeTurnId?: string | null,
): boolean {
  // Logical mid-turn steer turn ends only on turn.ended (issue #1300).
  // Intermediate harness ``done`` must NOT close the live socket or the
  // Dashboard misses drain continuation + falsely flushes the local queue.
  if (data.type === "turn.ended") return true;
  if (data.type === "error" || data.type === "hitl_required") return true;
  if (data.type !== "done") return false;
  if (activeTurnId) return false;
  const speaker = chunkSpeakerId(data, hostAgentId);
  if (!speaker) return true;
  const host = (hostAgentId || "").trim();
  // Room id not remembered yet — treat a stamped done as the 1:1 host.
  if (!host) return true;
  return speaker === host;
}

export function findLastToolMessageIndex(
  state: SessionStreamState,
  speaker?: string,
): number {
  const hostId = sessionHostAgentId(state);
  for (let i = state.messages.length - 1; i >= 0; i--) {
    const m = state.messages[i];
    if (
      m.role === "assistant" &&
      m.toolData &&
      sameStreamingSpeaker(
        m.speakerAgentId,
        speaker,
        hostId,
        Boolean(state.isTeamRoom),
      )
    ) {
      return i;
    }
  }
  return -1;
}

export function handleHarnessChunk(
  state: SessionStreamState,
  chunk: HarnessChunk,
  sessionId?: string,
): void {
  const speaker = chunkSpeakerId(chunk, sessionHostAgentId(state, sessionId));
  if (sessionId && (state.isStreaming || speaker)) {
    touchStreamActivity(sessionId);
  }
  switch (chunk.type) {
    case "token": {
      const snapshot = Boolean(chunk.team_snapshot);
      const liveCatchup = snapshot && Boolean(chunk.team_live);
      // A finished snapshot is a complete wall copy. A live catchup is the
      // text already spoken when the page refreshes; the member is still talking.
      if (!snapshot || liveCatchup) markSpeakerLive(state, speaker);
      appendStreamingToken(
        state,
        chunk.content,
        speaker,
        snapshot,
        Boolean(chunk.team_wrapup),
        liveCatchup,
        chunkTurnId(chunk),
      );
      if (snapshot && !liveCatchup) clearSpeakerLive(state, speaker);
      break;
    }
    case "reasoning":
      markSpeakerLive(state, speaker);
      appendStreamingReasoning(
        state,
        chunk.content,
        speaker,
        chunkTurnId(chunk),
      );
      break;
    case "usage":
      applyUsageChunk(state, chunk);
      break;
    case "tool_call_chunk":
      markSpeakerLive(state, speaker);
      upsertToolCall(state, chunk, sessionId, speaker);
      break;
    case "tool_result":
      // Keep the speaker live across the tool→next-token gap.
      markSpeakerLive(state, speaker);
      closeToolCall(state, chunk.messages, sessionId, speaker);
      break;
    case "done":
      if (!chunk.team_wrapup) {
        const pending =
          typeof chunk.pending_plan_path === "string"
            ? chunk.pending_plan_path.trim()
            : "";
        state.pendingPlanPath = pending || null;
      }
      if (chunk.team_wrapup) {
        finalizeWrapupMessages(state, speaker);
        clearSpeakerLive(state, speaker);
        // Wrap-up means members already finished — drop stale live bits
        // (e.g. snapshot re-marked a speaker after their done).
        pruneIdleLiveSpeakers(state);
        break;
      }
      if (chunk.hitl_paused === true) {
        // Another approval is waiting. Unlock the composer without dropping
        // parked steers or treating the resume as a finished turn.
        finalizeStreamingMessages(
          state,
          speaker,
          sessionHostAgentId(state, sessionId),
        );
        clearSpeakerLive(state, speaker);
        clearStreamingFlags(state, { keepSteer: true });
        if (sessionId) clearStreamActivity(sessionId);
        break;
      }
      finalizeStreamingMessages(
        state,
        speaker,
        sessionHostAgentId(state, sessionId),
      );
      if (typeof chunk.duration_ms === "number") {
        stampTurnDuration(state, chunk.duration_ms, speaker, sessionId);
      }
      clearSpeakerLive(state, speaker);
      // Host done seals the segment. When a logical steer turn is still
      // active, keep isStreaming / activeTurnId so 排队 stays available and
      // local follow-up flush does not race the server continuation.
      if (!speaker || (!hasStreamingMessages(state) && state.isStreaming)) {
        if (state.activeTurnId) {
          if (sessionId) touchStreamActivity(sessionId);
        } else {
          clearStreamingFlags(state);
          clearStreamActivity(sessionId ?? "");
        }
      }
      break;
    case "error":
      appendErrorBubble(state, chunk.message, chunk.error_code);
      break;
    case "hitl_required":
      handleHitlRequired(state, chunk.request, speaker);
      break;
    case "slash_action":
      emitSlashAction({
        action: chunk.action,
        agent_id: chunk.agent_id,
        sessionId,
        mode: chunk.mode,
      });
      break;
    case "attachment": {
      const url = typeof chunk.url === "string" ? chunk.url : "";
      const previewUrl =
        typeof chunk.preview_url === "string" ? chunk.preview_url : url;
      const b64 = typeof chunk.data === "string" ? chunk.data : "";
      const mime =
        typeof chunk.mime_type === "string"
          ? chunk.mime_type
          : "application/octet-stream";
      const displayUrl =
        previewUrl || (b64 ? `data:${mime};base64,${b64}` : "");
      if (!displayUrl) break;
      const kindRaw = typeof chunk.kind === "string" ? chunk.kind : "file";
      const toolIdx = findLastToolMessageIndex(state, speaker);
      const textIdx = findSpeakerTextToContinue(
        state.messages,
        speaker,
        sessionHostAgentId(state, sessionId),
      );
      const targetIdx = toolIdx >= 0 ? toolIdx : textIdx;
      const attachment = {
        url: displayUrl,
        kind: (kindRaw === "image" ? "image" : "file") as "image" | "file",
        filename:
          typeof chunk.filename === "string" ? chunk.filename : undefined,
        mediaType: mime !== "application/octet-stream" ? mime : undefined,
      };
      if (targetIdx >= 0) {
        const target = state.messages[targetIdx];
        const attachments = [...(target.attachments || []), attachment];
        state.messages = [
          ...state.messages.slice(0, targetIdx),
          { ...target, attachments },
          ...state.messages.slice(targetIdx + 1),
        ];
      } else {
        state.messages = [
          ...state.messages,
          {
            id: generateId(),
            role: "assistant",
            content: "",
            attachments: [attachment],
            status: "streaming",
            timestamp: Date.now(),
            speakerAgentId: speaker,
          },
        ];
      }
      break;
    }
    case "state_update":
    case "state_snapshot":
      updateContextUsageFromChunk(state, chunk);
      break;
    case "custom":
      // Decision runs on the host model call and the frame has no speaker.
      // In a team room an unlabeled chip would sit on its own invisible turn.
      // A wrap-up evaluation is a new host turn, not a rewrite of the dispatch.
      applyDecisionNotice(
        state,
        chunk.data,
        speaker ||
          (state.isTeamRoom ? sessionHostAgentId(state, sessionId) : undefined),
        Boolean(chunk.team_wrapup),
      );
      break;
  }
  if (chunkPaintsImmediately(chunk.type)) notify(state);
  else notifyStreamingPaint(state);
}

export /** Attach the latest decision result to this turn. One chip, updated in place. */
function applyDecisionNotice(
  state: SessionStreamState,
  data: unknown,
  speakerAgentId?: string,
  wrapup = false,
): void {
  const notice = parseDecisionNotice(data);
  if (!notice) return;
  const speaker = speakerAgentId?.trim() || undefined;
  const hostId = sessionHostAgentId(state);
  const teamRoom = Boolean(state.isTeamRoom);
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const message = state.messages[index];
    if (message.role === "user") break;
    if (message.role !== "assistant" || message.toolData || message.hitlData) {
      continue;
    }
    if (wrapup ? !message.teamWrapup : Boolean(message.teamWrapup)) continue;
    if (
      !sameStreamingSpeaker(message.speakerAgentId, speaker, hostId, teamRoom)
    ) {
      continue;
    }
    if (!message.decision) continue;
    state.messages = [
      ...state.messages.slice(0, index),
      { ...message, decision: notice },
      ...state.messages.slice(index + 1),
    ];
    return;
  }
  if (wrapup) {
    const wrapIdx = findWrapupTextToContinue(state.messages, speaker, hostId);
    if (wrapIdx >= 0) {
      const target = state.messages[wrapIdx];
      state.messages = [
        ...state.messages.slice(0, wrapIdx),
        { ...target, decision: notice },
        ...state.messages.slice(wrapIdx + 1),
      ];
      return;
    }
    markSpeakerLive(state, speaker);
    state.messages = [
      ...state.messages,
      {
        id: generateId(),
        role: "assistant",
        content: "",
        status: "streaming",
        timestamp: Date.now(),
        speakerAgentId: speaker,
        teamWrapup: true,
        decision: notice,
      },
    ];
    return;
  }
  const idx = findSpeakerTextToContinue(
    state.messages,
    speaker,
    hostId,
    continueTokenOpts(state),
  );
  if (idx >= 0) {
    const target = state.messages[idx];
    state.messages = [
      ...state.messages.slice(0, idx),
      { ...target, decision: notice },
      ...state.messages.slice(idx + 1),
    ];
    return;
  }
  markSpeakerLive(state, speaker);
  state.messages = [
    ...state.messages,
    {
      id: generateId(),
      role: "assistant",
      content: "",
      status: "streaming",
      timestamp: Date.now(),
      speakerAgentId: speaker,
      decision: notice,
    },
  ];
}

/** Apply one live harness frame (used by WS and unit tests). */
export function ingestHarnessChunk(
  sessionId: string,
  chunk: HarnessChunk,
  roomAgentId?: string,
): void {
  const state = getOrCreate(sessionId);
  rememberRoomAgent(state, roomAgentId);
  handleHarnessChunk(state, chunk, sessionId);
}
