/**
 * Per-session state cache: the session map, snapshot construction, speaker-live bookkeeping and history epoch.
 */

import { type SessionSnapshot, type SessionStreamState } from "./sseHelpers";
import { type UsageChunk } from "../../../utils/parseHarnessChunk";
import { isPausedAskTool } from "../utils/pendingHitl";
import { inFlightTail } from "../utils/mergeHistoryTail";
import { flushInflightTail } from "../utils/inflightTranscriptCache";

export function sealInFlightAssistantMessages(state: SessionStreamState): void {
  state.messages = state.messages.map((m) =>
    m.status === "streaming" ? { ...m, status: "done" as const } : m,
  );
  clearAllLiveSpeakers(state);
}

export /** Default snapshot for sessions that don't exist yet. Stable reference. */
const EMPTY_SNAPSHOT: SessionSnapshot = Object.freeze({
  messages: [],
  isStreaming: false,
  thinkingStartedAt: null,
  runUsage: null,
  contextUsage: null,
  historyHasMore: false,
  historyLoadingMore: false,
  historyNextOffset: 0,
  historyHydrated: false,
  pendingPlanPath: null,
  liveSpeakers: [] as string[],
  activeTurnId: null,
});

export const sessionStates = new Map<string, SessionStreamState>();

export let nextHistoryEpoch = 0;

export function flushLiveInflight(): void {
  for (const [sessionId, state] of sessionStates) {
    const live =
      state.isStreaming ||
      state.liveSpeakers.size > 0 ||
      state.messages.some((message) => message.status === "streaming") ||
      state.messages.some((m) => m.localPending);
    if (!live) continue;
    flushInflightTail(sessionId, inFlightTail(state.messages));
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", flushLiveInflight);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushLiveInflight();
  });
}

export /** Per-call samples let reconnects replace replayed usage instead of double-counting. */
const usageSamplesByState = new WeakMap<
  SessionStreamState,
  Map<string, UsageChunk["usage"]>
>();

export function buildSnapshot(state: SessionStreamState): SessionSnapshot {
  return {
    messages: state.messages,
    isStreaming: state.isStreaming,
    thinkingStartedAt: state.thinkingStartedAt,
    runUsage: state.runUsage,
    contextUsage: state.contextUsage,
    historyHasMore: state.historyHasMore,
    historyLoadingMore: state.historyLoadingMore,
    historyNextOffset: state.historyNextOffset,
    historyNextCursor: state.historyNextCursor,
    historyHydrated: state.historyHydrated,
    pendingPlanPath: state.pendingPlanPath ?? null,
    liveSpeakers: [...state.liveSpeakers].sort(),
    activeTurnId: state.activeTurnId ?? null,
  };
}

export function speakerLiveKey(speaker?: string): string {
  return (speaker || "").trim();
}

export /** Mark a speaker as still generating (survives tool gaps until ``done``). */
function markSpeakerLive(state: SessionStreamState, speaker?: string): void {
  const key = speakerLiveKey(speaker);
  state.liveSpeakers.add(key);
  // Unlabeled host frames also light up the room id so stamped host groups match.
  if (!key) {
    const host = state.roomAgentId?.trim();
    if (host) state.liveSpeakers.add(host);
  }
}

export function clearSpeakerLive(state: SessionStreamState, speaker?: string): void {
  const key = speakerLiveKey(speaker);
  state.liveSpeakers.delete(key);
  const host = state.roomAgentId?.trim();
  // Unlabeled and stamped host share one live bit — clear both together.
  if (!key) {
    if (host) state.liveSpeakers.delete(host);
  } else if (host && key === host) {
    state.liveSpeakers.delete("");
  }
}

export function clearAllLiveSpeakers(state: SessionStreamState): void {
  state.liveSpeakers.clear();
}

export /** Drop live speakers with no streaming text and no in-flight tools. */
function pruneIdleLiveSpeakers(state: SessionStreamState): void {
  if (state.liveSpeakers.size === 0) return;
  const busy = new Set<string>();
  const host = state.roomAgentId?.trim();
  for (const message of state.messages) {
    if (message.role !== "assistant") continue;
    const key = speakerLiveKey(message.speakerAgentId);
    const inFlightTool = Boolean(
      message.toolData &&
        message.toolData.output === undefined &&
        !isPausedAskTool(message),
    );
    if (message.status !== "streaming" && !inFlightTool) continue;
    busy.add(key);
    if (!key && host) busy.add(host);
    if (key && host && key === host) busy.add("");
  }
  for (const key of [...state.liveSpeakers]) {
    if (!busy.has(key)) state.liveSpeakers.delete(key);
  }
}

export function getOrCreate(sessionId: string): SessionStreamState {
  let state = sessionStates.get(sessionId);
  if (!state) {
    state = {
      sessionKey: sessionId,
      messages: [],
      historyEpoch: ++nextHistoryEpoch,
      isStreaming: false,
      thinkingStartedAt: null,
      runUsage: null,
      contextUsage: null,
      abortController: null,
      streamMsg: "",
      streamId: "",
      streamBlockType: "",
      toolCallIdIndex: {},
      historyHasMore: false,
      historyNextOffset: 0,
      historyLoadingMore: false,
      historyHydrated: false,
      historyStale: false,
      pendingPlanPath: null,
      listeners: new Set(),
      _snapshot: EMPTY_SNAPSHOT,
      roomAgentId: undefined,
      isTeamRoom: false,
      liveSpeakers: new Set(),
      activeTurnId: null,
      activeTurnUserId: null,
      pendingSteers: [],
    };
    sessionStates.set(sessionId, state);
  }
  if (!state.sessionKey || !sessionId.startsWith("__")) {
    state.sessionKey = sessionId;
  }
  if (!state.pendingSteers) state.pendingSteers = [];
  return state;
}

export function clearStreamingFlags(
  state: SessionStreamState,
  opts?: { keepSteer?: boolean },
): void {
  // Do not clear liveSpeakers — team members may keep generating after the
  // host turn unlocks the composer; process panels key off liveSpeakers.
  state.isStreaming = false;
  state.thinkingStartedAt = null;
  if (opts?.keepSteer) return;
  state.activeTurnId = null;
  // Team members and the host wrap-up keep talking after the host turn ends.
  if (!state.isTeamRoom) state.activeTurnUserId = null;
  state.pendingSteers = [];
}

export function hasStreamingMessages(state: SessionStreamState): boolean {
  return state.messages.some((m) => m.status === "streaming");
}

/** Advance the history revision so an in-flight read is dropped on arrival. */
export function bumpHistoryEpoch(): number {
  return ++nextHistoryEpoch;
}
