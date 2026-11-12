import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../hooks/useChat";
import { findMessageHits, normalizeSearchQuery } from "./messageSearch";

function message(
  id: string,
  content: string,
  role: ChatMessage["role"] = "assistant",
): ChatMessage {
  return { id, role, content, timestamp: 0 };
}

describe("findMessageHits", () => {
  it("counts every occurrence in document order, case-insensitively", () => {
    const hits = findMessageHits(
      [
        message("m1", "Deploy 需要 deploy token", "user"),
        message("m2", "无关内容"),
        message("m3", "DEPLOY 完成"),
      ],
      "deploy",
    );

    expect(hits).toEqual([
      { messageId: "m1", occurrence: 0 },
      { messageId: "m1", occurrence: 1 },
      { messageId: "m3", occurrence: 0 },
    ]);
  });

  it("returns nothing for an empty or whitespace query", () => {
    const messages = [message("m1", "hello")];
    expect(findMessageHits(messages, "")).toEqual([]);
    expect(findMessageHits(messages, "   ")).toEqual([]);
  });

  it("skips tool and system payloads", () => {
    const hits = findMessageHits(
      [
        message("tool-1", "hello from stdout", "tool"),
        message("sys-1", "hello from system", "system"),
        message("m1", "hello from user", "user"),
      ],
      "hello",
    );
    expect(hits).toEqual([{ messageId: "m1", occurrence: 0 }]);
  });

  it("does not overlap matches inside one word", () => {
    expect(findMessageHits([message("m1", "aaaa")], "aa")).toHaveLength(2);
  });

  it("normalizes the query the same way both sides are compared", () => {
    expect(normalizeSearchQuery("  Hello  ")).toBe("hello");
  });
});
