import { beforeEach, describe, expect, it } from "vitest";
import type { Session } from "../hooks/useSessions";
import {
  readSessionSortMode,
  sortSessionsForDisplay,
  writeSessionSortMode,
} from "./sessionSortPrefs";

function session(id: string, name: string, updatedAt: string | null, pinned = false): Session {
  return {
    id,
    name,
    threadId: id,
    updatedAt,
    channelType: "dashboard",
    pinned,
  };
}

describe("sessionSortPrefs", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("defaults to recent and persists a chosen mode", () => {
    expect(readSessionSortMode()).toBe("recent");
    writeSessionSortMode("name");
    expect(readSessionSortMode()).toBe("name");
    writeSessionSortMode("recent");
    expect(readSessionSortMode()).toBe("recent");
  });

  it("sorts by recency, newest first", () => {
    const list = [
      session("a", "Older", "2026-01-01T00:00:00.000Z"),
      session("b", "Newer", "2026-03-01T00:00:00.000Z"),
    ];
    expect(sortSessionsForDisplay(list, "recent").map((s) => s.id)).toEqual([
      "b",
      "a",
    ]);
  });

  it("sorts by name with numeric awareness", () => {
    const list = [
      session("a", "会话 10", "2026-01-01T00:00:00.000Z"),
      session("b", "会话 2", "2026-02-01T00:00:00.000Z"),
    ];
    expect(
      sortSessionsForDisplay(list, "name", "zh-Hans").map((s) => s.name),
    ).toEqual(["会话 2", "会话 10"]);
  });

  it("keeps pinned sessions above the chosen order", () => {
    const list = [
      session("a", "Alpha", "2026-03-01T00:00:00.000Z"),
      session("b", "Beta", "2026-01-01T00:00:00.000Z", true),
    ];
    expect(sortSessionsForDisplay(list, "recent").map((s) => s.id)).toEqual([
      "b",
      "a",
    ]);
    expect(sortSessionsForDisplay(list, "name").map((s) => s.id)).toEqual([
      "b",
      "a",
    ]);
  });
});
