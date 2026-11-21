import type { Session } from "../hooks/useSessions";

/** 命令面板只列 5 条：再多就不像「快速切换」，而像会话列表了。 */
export const RECENT_SESSION_LIMIT = 5;

function lastActiveAt(session: Session): number {
  if (!session.updatedAt) return 0;
  const parsed = Date.parse(session.updatedAt);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * 从「已加载」的会话列表里挑最近访问的几条，不发额外请求。
 * 注意不能直接沿用侧栏顺序：侧栏把收藏置顶，而这里要的是纯时间序。
 */
export function pickRecentSessions(
  sessions: readonly Session[],
  limit: number = RECENT_SESSION_LIMIT,
): Session[] {
  const max = Math.max(0, limit);
  if (max === 0) return [];
  return [...sessions]
    .sort(
      (a, b) => lastActiveAt(b) - lastActiveAt(a) || a.id.localeCompare(b.id),
    )
    .slice(0, max);
}
