import { describe, expect, it } from "vitest";

import {
  CHAT_SHORTCUTS,
  formatShortcut,
  shortcutSignature,
  type ChatShortcutId,
} from "./chatShortcuts";

describe("CHAT_SHORTCUTS", () => {
  it("lists every shortcut the help panel promises", () => {
    const ids = CHAT_SHORTCUTS.map((row) => row.id);
    const required: ChatShortcutId[] = [
      "send",
      "newline",
      "newChat",
      "palette",
      "search",
      "help",
      "close",
    ];
    expect(ids).toEqual(required);
  });

  it("has no duplicate accelerators", () => {
    const signatures = CHAT_SHORTCUTS.map((row) => shortcutSignature(row.keys));
    expect(new Set(signatures).size).toBe(signatures.length);
  });
});

describe("formatShortcut", () => {
  it("renders Windows/Linux chords with separators", () => {
    expect(formatShortcut(["mod", "shift", "o"], false)).toBe(
      "Ctrl + Shift + O",
    );
    expect(formatShortcut(["shift", "enter"], false)).toBe("Shift + Enter");
  });

  it("follows macOS modifier order", () => {
    expect(formatShortcut(["mod", "shift", "o"], true)).toBe("⇧⌘O");
    expect(formatShortcut(["mod", "/"], true)).toBe("⌘/");
    expect(formatShortcut(["esc"], true)).toBe("Esc");
  });
});
