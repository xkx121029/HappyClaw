import type { OctopAgent } from "../../context/AgentContext";
import type { OctopThread } from "../../api/modules/octopThreads";
import { parseToolExecutionFeedback } from "../../utils/toolMediaBlocks";

/** Which slice of the agent runtime an activity event belongs to. */
export type HomeEventKind =
  | "turn"
  | "tool"
  | "file"
  | "device"
  | "plugin"
  | "error"
  | "hitl";

export type HomeEventStatus = "running" | "done" | "failed";

export interface HomeEvent {
  /** Stable client id; tool calls reuse the harness tool-call id. */
  id: string;
  /** Client receive time, epoch milliseconds. */
  at: number;
  kind: HomeEventKind;
  /** Raw tool name for tool events, empty for turn/error events. */
  toolName?: string;
  /** Extra line shown under the title (plugin name, error message, prompt). */
  detail?: string;
  agentId: string;
  agentName: string;
  threadId: string;
  threadTitle: string;
  status: HomeEventStatus;
  /** Duration in ms once a tool result arrived. */
  durationMs?: number;
}

export interface HomeSession {
  agentId: string;
  agentName: string;
  threadId: string;
  title: string;
  /** Epoch milliseconds. 0 when the thread has never been used. */
  lastActive: number;
  turnActive: boolean;
  awaitingUser: boolean;
  /** Thread-level model override; ``null`` means the agent default (auto). */
  modelRef?: string | null;
}

/**
 * Beam colour class. Each value maps 1:1 to a real harness frame:
 * ``reasoning`` → think, ``tool_call_chunk`` → tool, ``token`` → text,
 * ``done`` → done, ``error`` → error.
 */
export type HomeTone = "think" | "tool" | "text" | "done" | "error";

/** One visual pulse. Kept out of React state until a throttled flush. */
export interface HomeTick {
  id: number;
  /** Client receive time, epoch milliseconds. */
  at: number;
  tone: HomeTone;
  /** Thread that produced the frame; maps the pulse to a ring segment. */
  threadId: string;
  /** Operation identity (tool-call id, or the tone for stream frames). */
  opKey: string;
  /** Concrete operation name for the beam label (tool display name). */
  label?: string;
}

/** Cross-session collaboration signal read from a team room frame. */
export type HomeLinkKind = "relay" | "summary" | "handoff";

export interface HomeLink {
  id: number;
  /** Client receive time, epoch milliseconds. */
  at: number;
  /** Speaking agent from the stamped frame (``agent_id``). */
  fromAgentId: string;
  /** Room thread the frame was pushed to. */
  toThreadId: string;
  kind: HomeLinkKind;
}

/** Upper bound on buffered pulses; older frames simply drop. */
export const HOME_TICK_LIMIT = 60;
export const HOME_LINK_LIMIT = 12;

/**
 * Ring segments. Above this the oldest idle sessions are folded into one
 * aggregate segment so 30+ sessions stay readable instead of blurring.
 */
export const HOME_RING_SESSION_LIMIT = 24;

export const HOME_EVENT_LIMIT = 120;
export const HOME_SESSION_LIMIT = 8;
/** Raw thread rows considered for the ring before folding into segments. */
export const HOME_RING_SOURCE_LIMIT = HOME_RING_SESSION_LIMIT * 4;
export const HOME_MAX_WATCHED_THREADS = 4;
/** Idle threads touched within this window stay subscribed so the first tool
 * call of the next turn is not missed while the page is open. */
export const HOME_RECENT_WATCH_MS = 10 * 60_000;

const FILE_TOOLS = new Set([
  "ls",
  "read_file",
  "write_file",
  "edit_file",
  "glob",
  "grep",
  "read_env_file",
  "write_env_file",
  "execute",
  "send_file_to_user",
]);

const DEVICE_PREFIXES = [
  "phone_",
  "remote_",
  "device_",
  "android_",
  "adb_",
  "desktop_",
];

/**
 * Map a tool name to a feed category.
 *
 * Plugin membership comes from ``GET /api/agents/{id}/tool-settings``; device
 * actions are the local direct-connect tools (``phone_*`` / ``desktop_*``).
 * Everything else stays a generic tool event.
 */
export function classifyTool(
  name: string,
  pluginTools: ReadonlySet<string> = new Set(),
): HomeEventKind {
  const tool = name.trim();
  if (!tool) return "tool";
  if (pluginTools.has(tool)) return "plugin";
  if (FILE_TOOLS.has(tool)) return "file";
  if (DEVICE_PREFIXES.some((prefix) => tool.startsWith(prefix))) {
    return "device";
  }
  return "tool";
}

/** Convert the thread API's unix-seconds (or ms) timestamp to epoch ms. */
export function normalizeTimestamp(value: number | null | undefined): number {
  if (!value || !Number.isFinite(value) || value <= 0) return 0;
  return value < 1_000_000_000_000 ? value * 1000 : value;
}

/** Flatten per-agent thread lists into the Home session window. */
export function mergeSessions(
  agents: readonly OctopAgent[],
  threadsByAgent: ReadonlyMap<string, readonly OctopThread[]>,
  limit = HOME_SESSION_LIMIT,
): HomeSession[] {
  const rows: HomeSession[] = [];
  for (const agent of agents) {
    const threads = threadsByAgent.get(agent.agent_id) ?? [];
    for (const thread of threads) {
      const lastActive = normalizeTimestamp(thread.last_active);
      const turnActive = thread.turn_active === true;
      const awaitingUser = thread.awaiting_user === true;
      rows.push({
        agentId: agent.agent_id,
        agentName: agent.name,
        threadId: thread.thread_id,
        title: thread.title?.trim() || thread.thread_id,
        lastActive,
        turnActive,
        awaitingUser,
        modelRef: thread.model_ref ?? null,
      });
    }
  }
  rows.sort((a, b) => {
    const rankA = a.awaitingUser ? 2 : a.turnActive ? 3 : 1;
    const rankB = b.awaitingUser ? 2 : b.turnActive ? 3 : 1;
    if (rankA !== rankB) return rankB - rankA;
    return b.lastActive - a.lastActive;
  });
  return rows.slice(0, limit);
}

/** One arc of the activity ring: a running conversation, or the folded rest. */
export interface RingSegment {
  /** Stable key: the thread id, or ``overflow`` for the aggregate arc. */
  key: string;
  title: string;
  agentId: string;
  agentName: string;
  /** Set for single-session arcs; ``null`` on the aggregate. */
  threadId: string | null;
  /** Every thread this arc stands for (used to route live pulses). */
  threadIds: string[];
  turnActive: boolean;
  awaitingUser: boolean;
  /** Model override for the conversation (menu shows the current value). */
  modelRef?: string | null;
  /** Folded conversation count; 0 for a single-session arc. */
  overflow: number;
}

/**
 * Divide the ring into one arc per **running** conversation.
 *
 * Only ``turn_active`` threads enter the ring; a finished turn leaves it, which
 * is why the ring can be empty. Order is by thread id (monotonic in this
 * codebase) so an added thread shifts arcs instead of reshuffling them. Above
 * ``limit`` the tail is folded into one hatched aggregate arc.
 */
export function buildRingSessions(
  sessions: readonly HomeSession[],
  limit = HOME_RING_SESSION_LIMIT,
): RingSegment[] {
  const running = sessions
    .filter((session) => session.turnActive)
    .sort((a, b) =>
      a.threadId < b.threadId ? -1 : a.threadId > b.threadId ? 1 : 0,
    );
  const toSegment = (session: HomeSession): RingSegment => ({
    key: session.threadId,
    title: session.title,
    agentId: session.agentId,
    agentName: session.agentName,
    threadId: session.threadId,
    threadIds: [session.threadId],
    turnActive: session.turnActive,
    awaitingUser: session.awaitingUser,
    modelRef: session.modelRef ?? null,
    overflow: 0,
  });

  if (limit < 1) return [];
  if (running.length <= limit) return running.map(toSegment);

  const segments = running.slice(0, limit - 1).map(toSegment);
  const folded = running.slice(limit - 1);
  segments.push({
    key: "overflow",
    title: "",
    agentId: "",
    agentName: "",
    threadId: null,
    threadIds: folded.map((session) => session.threadId),
    turnActive: true,
    awaitingUser: false,
    overflow: folded.length,
  });
  return segments;
}

/**
 * Half-ring geometry: the arc opens towards the right edge, so the visible
 * half spans π/2 → 3π/2. Slots tile this window and wrap at its two open ends.
 */
export const HOME_ARC_START = Math.PI / 2;
export const HOME_ARC_SWEEP = Math.PI;

/**
 * Map an absolute pointer angle to an arc index.
 *
 * The ring has exactly one global rotation and equal arcs, so the mapping is
 * ``mod(angle - start - rotation, sweep) / span``. Keeping it pure means the
 * right-click target can be tested (and is never derived from per-arc animated
 * positions). Defaults keep the full-circle mapping available.
 */
export function segmentIndexAt(
  angle: number,
  rotation: number,
  count: number,
  start = 0,
  sweep = Math.PI * 2,
): number {
  if (count <= 0) return -1;
  const span = sweep / count;
  const local = ((angle - start - rotation) % sweep + sweep) % sweep;
  return Math.min(count - 1, Math.floor(local / span));
}

/**
 * Threads whose live chat WebSocket the Home page should subscribe to.
 *
 * Active turns always win; the remaining slots go to threads touched in the
 * last ten minutes so the stream starts before the user's next tool call.
 */
export function watchTargets(
  sessions: readonly HomeSession[],
  now = Date.now(),
): HomeSession[] {
  const active: HomeSession[] = [];
  const recent: HomeSession[] = [];
  for (const session of sessions) {
    if (session.turnActive || session.awaitingUser) {
      active.push(session);
    } else if (
      session.lastActive > 0 &&
      now - session.lastActive <= HOME_RECENT_WATCH_MS
    ) {
      recent.push(session);
    }
  }
  return [...active, ...recent].slice(0, HOME_MAX_WATCHED_THREADS);
}

/** Insert or replace an event, keeping newest first and the list bounded. */
export function upsertEvent(
  events: readonly HomeEvent[],
  event: HomeEvent,
  limit = HOME_EVENT_LIMIT,
): HomeEvent[] {
  const next = events.filter((item) => item.id !== event.id);
  next.unshift(event);
  return next.slice(0, limit);
}

/** Patch a single event in place; no-op when it already scrolled out. */
export function patchEvent(
  events: readonly HomeEvent[],
  id: string,
  patch: Partial<HomeEvent>,
): HomeEvent[] {
  let changed = false;
  const next = events.map((item) => {
    if (item.id !== id) return item;
    changed = true;
    return { ...item, ...patch };
  });
  return changed ? next : (events as HomeEvent[]);
}

/** Count events received in the trailing window (default 60s). */
export function eventsPerMinute(
  events: readonly HomeEvent[],
  now: number,
  windowMs = 60_000,
): number {
  const cutoff = now - windowMs;
  let count = 0;
  for (const event of events) {
    if (event.at >= cutoff) count += 1;
  }
  return count;
}

/** One tool outcome inside a harness ``tool_result`` frame. */
export interface ToolResultEntry {
  /** ``tool_call_id``; absent on legacy payloads. */
  callId?: string;
  output: string;
  failed: boolean;
}

/**
 * Split a ``tool_result`` frame into per-tool outcomes.
 *
 * A frame is not one tool outcome: the harness may resend the whole
 * tool-message history after a call (see
 * ``infra/gateway/process/stream_project.py`` — "Full-history updates that
 * arrive after the call still contain every prior ToolMessage"). Judging the
 * frame as a whole marks every successful call failed as soon as one earlier
 * call errored.
 */
export function readToolResults(
  messages: readonly unknown[],
): ToolResultEntry[] {
  const entries: ToolResultEntry[] = [];
  for (const raw of messages) {
    if (!raw || typeof raw !== "object") continue;
    const obj = raw as Record<string, unknown>;
    const rawId = obj.tool_call_id ?? obj.toolCallId;
    const callId =
      typeof rawId === "string" && rawId.trim() ? rawId.trim() : undefined;
    const output = extractToolResultOutput([raw]);
    const failed =
      obj.status === "error" ||
      parseToolExecutionFeedback(output)?.isError === true;
    entries.push({ callId, output, failed });
  }
  return entries;
}

/** Best-effort text extraction from a single harness tool message. */
export function extractToolResultOutput(
  messages: readonly unknown[],
): string {
  const mediaTypes = new Set(["image", "file", "audio", "video"]);
  for (const raw of messages) {
    if (!raw || typeof raw !== "object") continue;
    const obj = raw as Record<string, unknown>;
    const content = obj.content;
    if (Array.isArray(content)) {
      const hasMedia = content.some(
        (part) =>
          part !== null &&
          typeof part === "object" &&
          mediaTypes.has(String((part as Record<string, unknown>).type || "")),
      );
      if (hasMedia) return JSON.stringify(content);
      const text = content
        .map((part) =>
          part !== null &&
          typeof part === "object" &&
          typeof (part as Record<string, unknown>).text === "string"
            ? String((part as Record<string, unknown>).text)
            : "",
        )
        .filter(Boolean)
        .join("\n");
      if (text) return text;
    }
    if (typeof content === "string" && content.trim()) return content;
    // Already-parsed JSON payloads (e.g. octop_ui envelopes) must not drop.
    if (content && typeof content === "object") return JSON.stringify(content);
    if (typeof obj.text === "string" && obj.text.trim()) return obj.text;
    for (const key of ["output", "artifact", "result"] as const) {
      const value = obj[key];
      if (typeof value === "string" && value) return value;
      if (value && typeof value === "object") return JSON.stringify(value);
    }
  }
  return "";
}

/** Short stable id for non-tool events (turn/error). */
export function makeEventId(
  prefix: string,
  threadId: string,
  at: number,
): string {
  return `${prefix}:${threadId}:${at}`;
}
