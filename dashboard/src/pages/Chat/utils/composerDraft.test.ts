import { afterEach, describe, expect, it } from "vitest";
import {
  COMPOSER_DRAFT_PREFIX,
  clearComposerDraft,
  composerDraftKey,
  readComposerDraft,
  writeComposerDraft,
} from "./composerDraft";

const KEY_A = composerDraftKey("agent-1", "thread-a");
const KEY_B = composerDraftKey("agent-1", "thread-b");
const KEY_NEW = composerDraftKey("agent-1", null);

afterEach(() => {
  for (const key of [KEY_A, KEY_B, KEY_NEW]) {
    localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  }
});

describe("composerDraft", () => {
  it("round-trips text and attachment metadata", () => {
    writeComposerDraft("agent-1", "thread-a", {
      text: "未发送的输入",
      attachments: [
        {
          url: "https://example.test/a.png",
          filename: "a.png",
          mediaType: "image/png",
          workspacePath: "uploads/a.png",
          kind: "image",
        },
      ],
    });

    const draft = readComposerDraft("agent-1", "thread-a");
    expect(draft.text).toBe("未发送的输入");
    expect(draft.attachments).toHaveLength(1);
    expect(draft.attachments[0]).toMatchObject({
      url: "https://example.test/a.png",
      filename: "a.png",
      kind: "image",
    });
  });

  it("keeps each session's draft isolated", () => {
    writeComposerDraft("agent-1", "thread-a", {
      text: "会话 A",
      attachments: [],
    });
    writeComposerDraft("agent-1", "thread-b", {
      text: "会话 B",
      attachments: [],
    });
    writeComposerDraft("agent-1", null, { text: "新会话", attachments: [] });

    expect(readComposerDraft("agent-1", "thread-a").text).toBe("会话 A");
    expect(readComposerDraft("agent-1", "thread-b").text).toBe("会话 B");
    expect(readComposerDraft("agent-1", null).text).toBe("新会话");
  });

  it("removes the stored entry when the draft is cleared", () => {
    writeComposerDraft("agent-1", "thread-a", {
      text: "待清空",
      attachments: [],
    });
    expect(localStorage.getItem(KEY_A)).not.toBeNull();

    clearComposerDraft("agent-1", "thread-a");

    expect(localStorage.getItem(KEY_A)).toBeNull();
    expect(readComposerDraft("agent-1", "thread-a")).toEqual({
      text: "",
      attachments: [],
    });
  });

  it("migrates the legacy sessionStorage text draft", () => {
    sessionStorage.setItem(KEY_A, "旧版草稿");

    expect(readComposerDraft("agent-1", "thread-a").text).toBe("旧版草稿");

    writeComposerDraft("agent-1", "thread-a", {
      text: "旧版草稿",
      attachments: [],
    });
    expect(localStorage.getItem(KEY_A)).not.toBeNull();
    expect(sessionStorage.getItem(KEY_A)).toBeNull();
  });

  it("falls back to an empty draft on corrupt JSON", () => {
    localStorage.setItem(KEY_A, "{not-json");

    expect(readComposerDraft("agent-1", "thread-a")).toEqual({
      text: "",
      attachments: [],
    });
  });

  it("uses the shared storage prefix so old keys keep working", () => {
    expect(KEY_A).toBe(`${COMPOSER_DRAFT_PREFIX}agent-1:thread-a`);
    expect(KEY_NEW).toBe(`${COMPOSER_DRAFT_PREFIX}agent-1:__new__`);
  });
});
