import { describe, expect, it } from "vitest";
import type { BaoTask } from "../../api/modules/bao";
import type { PairingRequest } from "../../api/modules/connectorPair";
import type { PendingHitlItem } from "../../api/modules/hitlPending";
import {
  countInbox,
  hitlItem,
  mergeInbox,
  pairingItem,
  reconcileInbox,
  sortInbox,
  taskItem,
} from "./homeInboxModel";

const NOW = 1_760_000_000_000;

function pairing(requestId: string, expiresInMs: number): PairingRequest {
  return {
    requestId,
    code: requestId.toUpperCase(),
    status: "pending",
    deviceId: "dev",
    deviceName: "Phone",
    platform: "ios",
    appVersion: "1.0",
    createdAtMs: NOW - 60_000,
    expiresAtMs: NOW + expiresInMs,
    reviewUrl: `/connector/pair/${requestId}?token=t`,
  };
}

function question(pendingId: string, createdAtMs = NOW): PendingHitlItem {
  return {
    pendingId,
    agentId: "agent-1",
    threadId: "thread-1",
    sessionTitle: "Weekly report",
    createdAtMs,
    kind: "question",
    questions: [],
    actionRequests: [{ name: "ask_user_question" }],
  };
}

function task(
  id: string,
  status: BaoTask["status"],
  createdAt: number,
): BaoTask {
  return {
    id,
    agent_id: "agent-1",
    agent_name: "Bao",
    thread_id: "thread-1",
    session_title: "Report",
    project_name: null,
    task_text: "build report",
    status,
    result_text: status === "done" ? "ok" : null,
    error_text: status === "failed" ? "boom" : null,
    created_at: createdAt,
    updated_at: createdAt,
    completed_at: createdAt,
    acknowledged_at: null,
  } as BaoTask;
}

describe("homeInboxModel", () => {
  it("puts open items first, then urgency, then newest", () => {
    const sorted = sortInbox([
      { ...taskItem(task("t1", "done", 100)), state: "acknowledged" as const },
      taskItem(task("t2", "failed", 300)),
      pairingItem(pairing("p1", 30_000), NOW),
      hitlItem(question("h1", NOW - 10_000)),
    ]);
    expect(sorted.map((item) => item.key)).toEqual([
      "pair:p1",
      "hitl:h1",
      "task:t2",
      "task:t1",
    ]);
  });

  it("merges without dropping handled context or resurrecting it", () => {
    const first = mergeInbox([], [hitlItem(question("h1"))]);
    const answered = [{ ...first[0], state: "answered" as const, answer: "yes" }];
    const merged = mergeInbox(answered, [hitlItem(question("h1"))]);
    expect(merged).toHaveLength(1);
    expect(merged[0].state).toBe("answered");
    expect(merged[0].answer).toBe("yes");

    const next = mergeInbox(merged, [pairingItem(pairing("p1", 60_000), NOW)]);
    expect(next).toHaveLength(2);
  });

  it("keeps a handled row but drops it from the unread count", () => {
    const items = mergeInbox(
      [],
      [
        pairingItem(pairing("p1", 60_000), NOW),
        hitlItem(question("h1")),
        taskItem(task("t1", "failed", 200)),
      ],
    );
    expect(countInbox(items)).toMatchObject({
      total: 3,
      pairing: 1,
      question: 1,
      task: 1,
      failed: 1,
    });

    const handled = items.map((item) =>
      item.key === "task:t1"
        ? { ...item, state: "acknowledged" as const }
        : item,
    );
    expect(countInbox(handled)).toMatchObject({ total: 2, task: 0, failed: 0 });
  });

  it("marks pending rows the server no longer reports as expired", () => {
    const items = mergeInbox(
      [],
      [pairingItem(pairing("p1", 60_000), NOW), hitlItem(question("h1"))],
    );
    const reconciled = reconcileInbox(
      items,
      new Set(["pairing"]),
      new Set(),
    );
    expect(reconciled.find((item) => item.key === "pair:p1")?.state).toBe(
      "expired",
    );
    expect(reconciled.find((item) => item.key === "hitl:h1")?.state).toBe(
      "pending",
    );
  });
});
