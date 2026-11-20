import { isMacPlatform } from "../utils/railShortcuts";

export type ShortcutToken =
  | "mod"
  | "shift"
  | "enter"
  | "esc"
  | "k"
  | "o"
  | "f"
  | "slash"
  | "question"
  | "comma"
  | "bracketLeft"
  | "bracketRight";

export interface ShortcutRow {
  id: string;
  labelKey: string;
  keys: ShortcutToken[];
  /** Fallback copy when the locale bundle has no entry yet. */
  label: string;
}

/**
 * Keys bound by the shell itself, i.e. available on every page.
 *
 * The chat page adds its own composer/navigation keys on top; this list is the
 * floor, so a user who has never opened a conversation still gets a complete
 * picture. Keep in sync with `MainLayout` and `pages/Chat/index.tsx`.
 */
export const SHELL_SHORTCUTS: ShortcutRow[] = [
  {
    id: "palette",
    labelKey: "shortcuts.palette",
    label: "命令面板 / 页面跳转",
    keys: ["mod", "k"],
  },
  {
    id: "help",
    labelKey: "shortcuts.help",
    label: "快捷键帮助",
    keys: ["question"],
  },
  {
    id: "close",
    labelKey: "shortcuts.close",
    label: "关闭当前面板",
    keys: ["esc"],
  },
];

/** Composer keys, only meaningful inside a conversation. */
export const COMPOSER_SHORTCUTS: ShortcutRow[] = [
  {
    id: "send",
    labelKey: "chat.shortcuts.send",
    label: "发送消息",
    keys: ["enter"],
  },
  {
    id: "newline",
    labelKey: "chat.shortcuts.newline",
    label: "换行",
    keys: ["shift", "enter"],
  },
  {
    id: "newChat",
    labelKey: "chat.shortcuts.newChat",
    label: "新建会话",
    keys: ["mod", "shift", "o"],
  },
  {
    id: "search",
    labelKey: "chat.shortcuts.search",
    label: "会话内搜索",
    keys: ["mod", "f"],
  },
  {
    id: "chatHelp",
    labelKey: "chat.shortcuts.help",
    label: "快捷键帮助",
    keys: ["mod", "slash"],
  },
];

const MODIFIERS = new Set<ShortcutToken>(["mod", "shift"]);

const MAC_LABELS: Record<ShortcutToken, string> = {
  mod: "⌘",
  shift: "⇧",
  enter: "Enter",
  esc: "Esc",
  k: "K",
  o: "O",
  f: "F",
  slash: "/",
  question: "?",
  comma: ",",
  bracketLeft: "[",
  bracketRight: "]",
};

const DEFAULT_LABELS: Record<ShortcutToken, string> = {
  mod: "Ctrl",
  shift: "Shift",
  enter: "Enter",
  esc: "Esc",
  k: "K",
  o: "O",
  f: "F",
  slash: "/",
  question: "?",
  comma: ",",
  bracketLeft: "[",
  bracketRight: "]",
};

/** macOS writes ⇧ left of ⌘; other platforms keep Ctrl + Shift + key. */
const MAC_RANK: Partial<Record<ShortcutToken, number>> = {
  shift: 0,
  mod: 1,
};

export function formatShortcutKeys(
  keys: readonly ShortcutToken[],
  isMac: boolean,
): string {
  if (!isMac) return keys.map((key) => DEFAULT_LABELS[key]).join(" + ");
  const modifiers = keys
    .filter((key) => MODIFIERS.has(key))
    .sort((a, b) => (MAC_RANK[a] ?? 9) - (MAC_RANK[b] ?? 9));
  const rest = keys.filter((key) => !MODIFIERS.has(key));
  return [...modifiers, ...rest].map((key) => MAC_LABELS[key]).join("");
}

/** Order-independent signature, used to assert no two rows collide. */
export function shortcutSignature(keys: readonly ShortcutToken[]): string {
  return [...keys].sort().join("+");
}

export function isMacUser(): boolean {
  return isMacPlatform();
}
