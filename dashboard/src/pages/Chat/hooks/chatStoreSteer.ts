/**
 * Mid-turn steer protocol: optimistic rows, withdrawal, remote user frames and busy-turn gating.
 */

import { generateId } from "../../../utils/messageParser";
import {
  type ChatAttachment,
  type ChatMessage,
  type SessionStreamState,
} from "./sseHelpers";
import { buildUserMessageContent } from "../utils/chatAttachments";
import { emitSharedTurnBusy, emitSteerRestore } from "./chatStoreEvents";
import { getOrCreate, sessionStates } from "./chatStoreState";
import { notify } from "./chatStorePublish";
import { liveSockets } from "./chatStoreSocket";
import {
  noteTurnOwner,
  noteTurnOwnerFromLatestUser,
  sealPriorStreamingAssistants,
} from "./chatStoreMessageBubbles";
import { beginStream } from "./chatStoreStream";

export function optimisticSteerMessageId(clientPendingId: string): string {
  return `steer:${clientPendingId}`;
}

export function steerClientIds(
  data: Record<string, unknown>,
  state: SessionStreamState,
): string[] {
  const raw = data.client_pending_ids;
  if (Array.isArray(raw) && raw.length > 0) {
    return raw.map((id) => String(id || "").trim()).filter(Boolean);
  }
  return state.pendingSteers.map((s) => s.clientPendingId);
}

export function optimisticAttachments(state: SessionStreamState): ChatAttachment[] {
  return state.messages.flatMap((message) =>
    message.id.startsWith("steer:") ? message.attachments ?? [] : [],
  );
}

export function attachmentsFromSteerFrame(raw: unknown): ChatAttachment[] | undefined {
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

export /** Commit shows the user row in the transcript immediately. */
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

export function findPendingSteer(
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

export function restoreWithdrawnSteer(
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

export /**
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

export function rejectSteerWithdrawal(
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

export /** Settle optimistic rows when their server fact arrives (drain/reject/end). */
function dropOptimisticSteerMessages(
  state: SessionStreamState,
  clientPendingIds: string[],
): void {
  const next = state.messages.filter(
    (m) => !clientPendingIds.some((c) => m.id === optimisticSteerMessageId(c)),
  );
  if (next.length !== state.messages.length) state.messages = next;
}

export function authorFromFrame(raw: unknown): ChatMessage["author"] {
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

export /** Show someone else's question as soon as their turn starts. */
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

export function applySteerProtocolFrame(
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
