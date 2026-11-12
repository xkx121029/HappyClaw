import { isMacPlatform } from "../../../utils/railShortcuts";

export type ChatShortcutToken =
  | "mod"
  | "shift"
  | "enter"
  | "esc"
  | "k"
  | "o"
  | "f"
  | "/";

export type ChatShortcutId =
  | "send"
  | "newline"
  | "newChat"
  | "palette"
  | "search"
  | "help"
  | "close";

export interface ChatShortcutRow {
  id: ChatShortcutId;
  labelKey: string;
  keys: ChatShortcutToken[];
}

/**
 * 只列真正挂在这个页面上的键位，顺序按使用频率。
 * 新增条目时请同步 Chat/index.tsx 的 keydown 分支，并保证组合键互不重复。
 */
export const CHAT_SHORTCUTS: ChatShortcutRow[] = [
  { id: "send", labelKey: "chat.shortcuts.send", keys: ["enter"] },
  {
    id: "newline",
    labelKey: "chat.shortcuts.newline",
    keys: ["shift", "enter"],
  },
  {
    id: "newChat",
    labelKey: "chat.shortcuts.newChat",
    keys: ["mod", "shift", "o"],
  },
  { id: "palette", labelKey: "chat.shortcuts.palette", keys: ["mod", "k"] },
  { id: "search", labelKey: "chat.shortcuts.search", keys: ["mod", "f"] },
  { id: "help", labelKey: "chat.shortcuts.help", keys: ["mod", "/"] },
  { id: "close", labelKey: "chat.shortcuts.close", keys: ["esc"] },
];

/** 与书写顺序无关的签名，用来检测两个快捷键是否撞车。 */
export function shortcutSignature(keys: readonly ChatShortcutToken[]): string {
  return [...keys].sort().join("+");
}

const MODIFIER_TOKENS = new Set<ChatShortcutToken>(["mod", "shift"]);

const MAC_LABELS: Record<ChatShortcutToken, string> = {
  mod: "⌘",
  shift: "⇧",
  enter: "Enter",
  esc: "Esc",
  k: "K",
  o: "O",
  f: "F",
  "/": "/",
};

const DEFAULT_LABELS: Record<ChatShortcutToken, string> = {
  mod: "Ctrl",
  shift: "Shift",
  enter: "Enter",
  esc: "Esc",
  k: "K",
  o: "O",
  f: "F",
  "/": "/",
};

/** macOS 习惯把 ⇧ 写在 ⌘ 左边，其它平台保持 Ctrl + Shift + 键 的写法。 */
const MAC_MODIFIER_RANK: Partial<Record<ChatShortcutToken, number>> = {
  shift: 0,
  mod: 1,
};

export function formatShortcut(
  keys: readonly ChatShortcutToken[],
  isMac: boolean,
): string {
  if (!isMac) return keys.map((key) => DEFAULT_LABELS[key]).join(" + ");
  const modifiers = keys
    .filter((key) => MODIFIER_TOKENS.has(key))
    .sort((a, b) => (MAC_MODIFIER_RANK[a] ?? 9) - (MAC_MODIFIER_RANK[b] ?? 9));
  const rest = keys.filter((key) => !MODIFIER_TOKENS.has(key));
  return [...modifiers, ...rest].map((key) => MAC_LABELS[key]).join("");
}

export function isMacUser(): boolean {
  return isMacPlatform();
}
