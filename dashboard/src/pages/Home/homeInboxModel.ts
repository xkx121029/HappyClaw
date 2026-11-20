import type { BaoTask } from "../../api/modules/bao";
import type { PairingRequest } from "../../api/modules/connectorPair";
import type { PendingHitlItem } from "../../api/modules/hitlPending";
import type { AskQuestion } from "../../api/types/hitl";

export type InboxSource = "pairing" | "question" | "approval" | "task";

export type InboxState =
  | "pending"
  | "approved"
  | "rejected"
  | "answered"
  | "acknowledged"
  | "followed_up"
  | "expired";

/** One actionable row in the Home inbox. */
export interface InboxItem {
  key: string;
  source: InboxSource;
  state: InboxState;
  /** Milliseconds, newest first inside one priority bucket. */
  createdAt: number;
  priority: number;
  agentId?: string;
  agentName?: string;
  threadId?: string;
  sessionTitle?: string | null;
  /** Phone pairing payload. */
  pairing?: PairingRequest;
  /** HITL payload. */
  pendingId?: string;
  questions?: AskQuestion[];
  actionNames?: string[];
  answer?: string;
  /** Bao task payload. */
  task?: BaoTask;
  reply?: string;
  /** Last action failure; cleared on the next successful attempt. */
  error?: string;
}

export interface InboxCounts {
  total: number;
  pairing: number;
  question: number;
  approval: number;
  task: number;
  failed: number;
}

const PAIRING_URGENT_MS = 2 * 60_000;
const PAIRING_SOON_MS = 10 * 60_000;

function pairingPriority(req: PairingRequest, now: number): number {
  const remaining = req.expiresAtMs - now;
  if (remaining <= PAIRING_URGENT_MS) return 120;
  if (remaining <= PAIRING_SOON_MS) return 110;
  return 100;
}

export function isOpen(item: InboxItem): boolean {
  return item.state === "pending";
}

export function pairingItem(req: PairingRequest, now = Date.now()): InboxItem {
  return {
    key: `pair:${req.requestId}`,
    source: "pairing",
    state: "pending",
    createdAt: req.createdAtMs || now,
    priority: pairingPriority(req, now),
    pairing: req,
  };
}

export function hitlItem(item: PendingHitlItem): InboxItem {
  return {
    key: `hitl:${item.pendingId}`,
    source: item.kind === "question" ? "question" : "approval",
    state: "pending",
    createdAt: item.createdAtMs,
    priority: item.kind === "question" ? 90 : 85,
    agentId: item.agentId,
    threadId: item.threadId,
    sessionTitle: item.sessionTitle,
    pendingId: item.pendingId,
    questions: item.questions,
    actionNames: item.actionRequests.map((action) => action.name),
  };
}

export function taskItem(task: BaoTask): InboxItem {
  const seconds = task.completed_at ?? task.updated_at ?? task.created_at;
  return {
    key: `task:${task.id}`,
    source: "task",
    state: "pending",
    createdAt: seconds * 1000,
    priority: task.status === "failed" ? 80 : 60,
    agentId: task.agent_id,
    agentName: task.agent_name,
    threadId: task.thread_id,
    sessionTitle: task.session_title,
    task,
  };
}

/** Unresolved first, then urgency, then newest. */
export function sortInbox(items: InboxItem[]): InboxItem[] {
  return [...items].sort((left, right) => {
    const leftOpen = isOpen(left) ? 1 : 0;
    const rightOpen = isOpen(right) ? 1 : 0;
    if (leftOpen !== rightOpen) return rightOpen - leftOpen;
    if (left.priority !== right.priority) return right.priority - left.priority;
    return right.createdAt - left.createdAt;
  });
}

/**
 * Upsert by key. A resolved row is never resurrected by a stale server copy,
 * and no existing row is dropped — handled context stays visible.
 */
export function mergeInbox(
  previous: InboxItem[],
  incoming: InboxItem[],
): InboxItem[] {
  const map = new Map(previous.map((item) => [item.key, item]));
  for (const item of incoming) {
    const old = map.get(item.key);
    if (!old) {
      map.set(item.key, item);
      continue;
    }
    map.set(item.key, {
      ...item,
      state:
        old.state !== "pending" && item.state === "pending"
          ? old.state
          : item.state,
      answer: item.answer ?? old.answer,
      reply: item.reply ?? old.reply,
      error: item.error,
    });
  }
  return Array.from(map.values());
}

export function patchInbox(
  items: InboxItem[],
  key: string,
  patch: Partial<InboxItem>,
): InboxItem[] {
  return items.map((item) => (item.key === key ? { ...item, ...patch } : item));
}

/**
 * Mark still-pending rows of *sources* that the server no longer reports as
 * expired. Rows handled locally (answer/approve/ack) keep their own state.
 */
export function reconcileInbox(
  items: InboxItem[],
  sources: ReadonlySet<InboxSource>,
  serverKeys: ReadonlySet<string>,
): InboxItem[] {
  return items.map((item) => {
    if (!sources.has(item.source) || !isOpen(item)) return item;
    if (serverKeys.has(item.key)) return item;
    return { ...item, state: "expired" };
  });
}

export function countInbox(items: InboxItem[]): InboxCounts {
  const counts: InboxCounts = {
    total: 0,
    pairing: 0,
    question: 0,
    approval: 0,
    task: 0,
    failed: 0,
  };
  for (const item of items) {
    if (!isOpen(item)) continue;
    counts.total += 1;
    counts[item.source] += 1;
    if (item.source === "task" && item.task?.status === "failed") {
      counts.failed += 1;
    }
  }
  return counts;
}
