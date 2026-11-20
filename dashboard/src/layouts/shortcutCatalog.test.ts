import { describe, expect, it } from "vitest";

import {
  COMPOSER_SHORTCUTS,
  SHELL_SHORTCUTS,
  formatShortcutKeys,
  shortcutSignature,
} from "./shortcutCatalog";

describe("shortcut catalog", () => {
  it("lists every global shortcut the cheatsheet promises", () => {
    expect(SHELL_SHORTCUTS.map((row) => row.id)).toEqual([
      "palette",
      "help",
      "close",
    ]);
  });

  it("lists the composer keys the chat page binds", () => {
    expect(COMPOSER_SHORTCUTS.map((row) => row.id)).toEqual([
      "send",
      "newline",
      "newChat",
      "search",
      "chatHelp",
    ]);
  });

  it("has no duplicate accelerators", () => {
    const signatures = [...SHELL_SHORTCUTS, ...COMPOSER_SHORTCUTS].map((row) =>
      shortcutSignature(row.keys),
    );
    expect(new Set(signatures).size).toBe(signatures.length);
  });

  it("falls back to the inline label when a locale key is missing", () => {
    for (const row of [...SHELL_SHORTCUTS, ...COMPOSER_SHORTCUTS]) {
      expect(row.label.length).toBeGreaterThan(0);
    }
  });
});

describe("formatShortcutKeys", () => {
  it("renders Windows/Linux chords with separators", () => {
    expect(formatShortcutKeys(["mod", "shift", "o"], false)).toBe(
      "Ctrl + Shift + O",
    );
    expect(formatShortcutKeys(["shift", "enter"], false)).toBe("Shift + Enter");
  });

  it("follows macOS modifier order", () => {
    expect(formatShortcutKeys(["mod", "shift", "o"], true)).toBe("⇧⌘O");
    expect(formatShortcutKeys(["mod", "slash"], true)).toBe("⌘/");
    expect(formatShortcutKeys(["esc"], true)).toBe("Esc");
  });
});
