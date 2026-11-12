import { describe, expect, it } from "vitest";

import type { Session } from "../hooks/useSessions";
import { pickRecentSessions } from "./recentSessions";

function session(
  id: string,
  updatedAt: string | null,
  extra: Partial<Session> = {},
): Session {
  return {
    id,
    name: id,
    threadId: `t-${id}`,
    updatedAt,
    channelType: "local",
    ...extra,
  };
}

describe("pickRecentSessions", () => {
  it("sorts by last activity and keeps only five", () => {
    const sessions = [
      session("a", "2026-11-01T10:00:00Z"),
      session("b", "2026-11-12T09:00:00Z"),
      session("c", "2026-11-05T09:00:00Z"),
      session("d", "2026-11-11T09:00:00Z"),
      session("e", "2026-11-02T09:00:00Z"),
      session("f", "2026-11-10T09:00:00Z"),
    ];

    expect(pickRecentSessions(sessions).map((item) => item.id)).toEqual([
      "b",
      "d",
      "f",
      "c",
      "e",
    ]);
  });

  it("ignores the sidebar's pinned-first order", () => {
    const pinnedOld = session("pinned", "2026-01-01T00:00:00Z", {
      pinned: true,
    });
    const fresh = session("fresh", "2026-11-12T00:00:00Z");
    expect(pickRecentSessions([pinnedOld, fresh])[0].id).toBe("fresh");
  });

  it("puts sessions without a timestamp last", () => {
    const result = pickRecentSessions([
      session("unknown", null),
      session("dated", "2026-11-01T00:00:00Z"),
    ]);
    expect(result.map((item) => item.id)).toEqual(["dated", "unknown"]);
  });

  it("does not mutate the caller's array", () => {
    const sessions = [
      session("old", "2026-01-01T00:00:00Z"),
      session("new", "2026-11-01T00:00:00Z"),
    ];
    const before = sessions.map((item) => item.id);
    pickRecentSessions(sessions);
    expect(sessions.map((item) => item.id)).toEqual(before);
  });
});
