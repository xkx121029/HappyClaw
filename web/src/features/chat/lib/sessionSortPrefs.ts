import type { Session } from "../hooks/useSessions";

export type SessionSortMode = "recent" | "name";

const STORAGE_KEY = "octop.chat.sessionSort";

/** 会话列表排序偏好：单人本机，直接存 localStorage，刷新后保持。 */
export function readSessionSortMode(): SessionSortMode {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === "name" ? "name" : "recent";
  } catch {
    return "recent";
  }
}

export function writeSessionSortMode(mode: SessionSortMode) {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // 隐私模式或存储被禁用时保持当前内存顺序，不阻断列表渲染。
  }
}

/**
 * 置顶永远在最前，其余按所选方式排序。
 * 名称排序带数字感知，避免「会话 10」排在「会话 2」前面。
 */
export function sortSessionsForDisplay(
  sessions: Session[],
  mode: SessionSortMode,
  locale?: string,
): Session[] {
  return [...sessions].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    if (mode === "name") {
      const byName = a.name.localeCompare(b.name, locale, {
        numeric: true,
        sensitivity: "base",
      });
      if (byName !== 0) return byName;
    } else {
      const ta = a.updatedAt ? Date.parse(a.updatedAt) : 0;
      const tb = b.updatedAt ? Date.parse(b.updatedAt) : 0;
      if (tb !== ta) return tb - ta;
    }
    return b.id.localeCompare(a.id);
  });
}
