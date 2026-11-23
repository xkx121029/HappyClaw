/**
 * History reads and message-list mutations: page load, prepend, restore, invalidation and local appends.
 */

import { generateId } from "../../../utils/messageParser";
import { type ChatMessage, type SessionStreamState } from "./sseHelpers";
import { preferLocalTranscript } from "../utils/mergeHistoryTail";
import { clearInflightTail } from "../utils/inflightTranscriptCache";
import {
  bumpHistoryEpoch,
  clearAllLiveSpeakers,
  clearStreamingFlags,
  getOrCreate,
  sessionStates,
  usageSamplesByState,
} from "./chatStoreState";
import { notify } from "./chatStorePublish";

/** Remember or clear the pending plan file for the PlanReady card. */
export function setPendingPlanPath(
  sessionId: string,
  path: string | null | undefined,
): void {
  const state = getOrCreate(sessionId);
  const next = (path || "").trim() || null;
  if ((state.pendingPlanPath ?? null) === next) return;
  state.pendingPlanPath = next;
  notify(state);
}

/** Directly set messages for a session (e.g. from loadHistory). */
export function setMessages(sessionId: string, messages: ChatMessage[]) {
  const state = getOrCreate(sessionId);
  state.messages = messages;
  state.runUsage = null;
  usageSamplesByState.delete(state);
  notify(state);
}

/** Replace messages and pagination cursor after an initial history load. */
export function setHistoryPage(
  sessionId: string,
  messages: ChatMessage[],
  opts: { hasMore: boolean; nextOffset: number; nextCursor?: string | null },
) {
  const state = getOrCreate(sessionId);
  state.messages = messages;
  state.runUsage = null;
  usageSamplesByState.delete(state);
  state.historyHasMore = opts.hasMore;
  state.historyNextOffset = opts.nextOffset;
  state.historyNextCursor = opts.nextCursor ?? null;
  state.historyLoadingMore = false;
  state.historyHydrated = true;
  state.historyStale = false;
  notify(state);
}

/** Put a cached in-flight tail back when it is longer than what is on screen. */
export function restoreInflightTail(
  sessionId: string,
  tail: ChatMessage[],
): void {
  const state = sessionStates.get(sessionId);
  if (!state || tail.length === 0) return;
  const next = preferLocalTranscript(state.messages, tail);
  if (next === state.messages) return;
  state.messages = next;
  notify(state);
}

/**
 * Mark history as stale so the next `loadHistory` refetches from the server.
 * A live turn owns the message list, so leave a streaming session untouched.
 * An idle listen socket (team follow-ups) must not block a stale refetch.
 * Messages and the hydration flag stay put: the reload replaces them once it
 * lands, which keeps the view from flashing an empty loading state.
 */
export function invalidateHistory(sessionId: string) {
  const state = sessionStates.get(sessionId);
  if (!state || !state.historyHydrated) return;
  if (state.isStreaming) return;
  state.historyStale = true;
}

/** True when a server push arrived after the last history fetch. */
export function isHistoryStale(sessionId: string): boolean {
  return sessionStates.get(sessionId)?.historyStale ?? false;
}

export function dedupePrependMessages(
  older: ChatMessage[],
  existing: ChatMessage[],
): ChatMessage[] {
  if (older.length === 0) return older;
  const seen = new Set(existing.map((message) => message.id));
  return older.filter((message) => !seen.has(message.id));
}

/** Prepend older messages when the user scrolls up. */
export function prependHistoryMessages(
  sessionId: string,
  older: ChatMessage[],
  opts: { hasMore: boolean; nextOffset: number; nextCursor?: string | null },
) {
  const state = getOrCreate(sessionId);
  const uniqueOlder = dedupePrependMessages(older, state.messages);
  if (uniqueOlder.length > 0) {
    state.messages = [...uniqueOlder, ...state.messages];
  }
  state.historyHasMore = opts.hasMore;
  state.historyNextOffset = opts.nextOffset;
  state.historyNextCursor = opts.nextCursor ?? null;
  notify(state);
}

export function setHistoryLoadingMore(sessionId: string, loading: boolean) {
  const state = getOrCreate(sessionId);
  state.historyLoadingMore = loading;
  notify(state);
}

/** Append a user message to a session. */
export function appendUserMessage(sessionId: string, msg: ChatMessage) {
  const state = getOrCreate(sessionId);
  if (state.messages.some((m) => m.id === msg.id)) return;
  state.messages = [...state.messages, { ...msg, localPending: true }];
  notify(state);
}

/**
 * Truncate all messages from messageId (inclusive) onwards, replacing that
 * message's content with newContent. Also aborts any in-flight stream.
 * Returns the new send's identity, or null if the message was not found.
 */
export function truncateAndReplaceUserMessage(
  sessionId: string,
  messageId: string,
  newContent: string,
): string | null {
  const state = getOrCreate(sessionId);
  const idx = state.messages.findIndex((m) => m.id === messageId);
  if (idx < 0) return null;

  // Abort any in-flight stream before rewriting history
  state.abortController?.abort();
  state.abortController = null;

  const original = state.messages[idx];
  const replacementId = generateId();
  state.historyEpoch = bumpHistoryEpoch();
  clearInflightTail(sessionId);
  state.messages = [
    ...state.messages.slice(0, idx),
    {
      ...original,
      id: replacementId,
      content: newContent,
      status: "done" as const,
      localPending: true,
    },
  ];
  clearStreamingFlags(state);
  state.runUsage = null;
  usageSamplesByState.delete(state);
  state.streamMsg = "";
  state.streamId = "";
  state.streamBlockType = "";
  state.toolCallIdIndex = {};
  notify(state);
  return replacementId;
}

/** Append a push (proactive/cron) assistant message to all active sessions. */
export function appendPushMessage(text: string) {
  const msg: ChatMessage = {
    id: generateId(),
    role: "assistant",
    content: text,
    timestamp: Date.now(),
  };
  // renameSessionKey may briefly alias two keys to one state — dedupe.
  const seen = new Set<SessionStreamState>();
  for (const state of sessionStates.values()) {
    if (seen.has(state)) continue;
    seen.add(state);
    state.messages = [...state.messages, msg];
    notify(state);
  }
}

/** Clear all messages for a session, unless a turn is still in flight. */
export function clearMessages(sessionId: string) {
  const state = getOrCreate(sessionId);
  // Leaving a thread (agent switch, page change) must not seal a live turn:
  // the socket keeps streaming into this state and the UI needs it on return.
  // An idle listen socket (team follow-ups) must not block a clear.
  if (state.isStreaming) return;
  state.historyEpoch = bumpHistoryEpoch();
  const alreadyEmpty =
    state.messages.length === 0 &&
    !state.isStreaming &&
    !state.historyHydrated &&
    state.historyNextOffset === 0 &&
    !state.historyHasMore;
  if (alreadyEmpty) return;
  state.messages = [];
  clearStreamingFlags(state);
  clearAllLiveSpeakers(state);
  state.runUsage = null;
  usageSamplesByState.delete(state);
  state.streamMsg = "";
  state.streamId = "";
  state.streamBlockType = "";
  state.toolCallIdIndex = {};
  state.historyHasMore = false;
  state.historyNextOffset = 0;
  state.historyNextCursor = null;
  state.historyLoadingMore = false;
  state.historyHydrated = false;
  state.historyStale = false;
  clearInflightTail(sessionId);
  notify(state);
}
