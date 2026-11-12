import { describe, expect, it } from "vitest";
import type { Session } from "../hooks/useSessions";
import { groupSessionsByRecency } from "./sessionGroups";

const NOW = Date.UTC(2026, 0, 8, 12, 0, 0); // 2026-01-08 12:00 UTC

function session(overrides: {
  id?: string;
  name?: string;
  updatedAt?: string | null;
  pinned?: boolean;
}): Session {
  return {
    id: overrides.id ?? "s",
    name: overrides.name ?? "会话",
    threadId: "t",
    agentId: "a",
    updatedAt: overrides.updatedAt ?? null,
    channelType: "dashboard",
    pinned: overrides.pinned ?? false,
    hasActivity: true,
  } as Session;
}

describe("groupSessionsByRecency", () => {
  it("按今天/昨天/过去7天/过去30天/更早分桶", () => {
    const groups = groupSessionsByRecency(
      [
        session({ id: "d", updatedAt: "2026-01-08T09:00:00Z" }),
        session({ id: "y", updatedAt: "2026-01-07T23:30:00Z" }),
        session({ id: "w", updatedAt: "2026-01-03T00:00:00Z" }),
        session({ id: "m", updatedAt: "2025-12-20T00:00:00Z" }),
        session({ id: "o", updatedAt: "2025-01-01T00:00:00Z" }),
        session({ id: "n", updatedAt: null }),
      ],
      "UTC",
      NOW,
    );
    expect(groups.map((g) => g.key)).toEqual([
      "today",
      "yesterday",
      "week",
      "month",
      "older",
    ]);
    expect(groups[0].sessions.map((s) => s.id)).toEqual(["d"]);
    expect(groups[4].sessions.map((s) => s.id)).toEqual(["o", "n"]);
  });

  it("置顶会话独立成组且排最前", () => {
    const groups = groupSessionsByRecency(
      [
        session({ id: "d", updatedAt: "2026-01-08T09:00:00Z" }),
        session({ id: "p", updatedAt: "2025-01-01T00:00:00Z", pinned: true }),
      ],
      "UTC",
      NOW,
    );
    expect(groups.map((g) => g.key)).toEqual(["pinned", "today"]);
    expect(groups[0].sessions.map((s) => s.id)).toEqual(["p"]);
  });

  it("空组不输出且组内保持输入顺序", () => {
    const groups = groupSessionsByRecency(
      [
        session({ id: "w1", updatedAt: "2026-01-05T00:00:00Z" }),
        session({ id: "w2", updatedAt: "2026-01-02T00:00:00Z" }),
      ],
      "UTC",
      NOW,
    );
    expect(groups.map((g) => g.key)).toEqual(["week"]);
    expect(groups[0].sessions.map((s) => s.id)).toEqual(["w1", "w2"]);
  });

  it("空输入返回空数组", () => {
    expect(groupSessionsByRecency([], "UTC", NOW)).toEqual([]);
  });
});
