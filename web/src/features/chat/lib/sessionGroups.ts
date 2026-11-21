/**
 * 会话列表按最近时间分组：置顶 / 今天 / 昨天 / 过去 7 天 / 过去 30 天 / 更早。
 * 纯函数无 i18n 依赖 —— 分组键由调用方映射文案。
 * 日界按传入时区计算（默认跟随服务端时区约定，由调用方传入），
 * 避免同一条会话在本地与服务端时区之间跳组。
 */
import type { Session } from "../hooks/useSessions";

export type SessionGroupKey =
  | "pinned"
  | "today"
  | "yesterday"
  | "week"
  | "month"
  | "older";

export interface SessionGroup {
  key: SessionGroupKey;
  sessions: Session[];
}

const DAY_MS = 86_400_000;

/**
 * 置顶优先，其次按更新时间倒序。跨专家平铺与按项目分组共用同一比较，
 * 避免两处排序规则漂移。
 */
export function compareSessionsByRecency(
  a: { pinned?: boolean; updatedAt?: string | null },
  b: { pinned?: boolean; updatedAt?: string | null },
): number {
  if (Boolean(a.pinned) !== Boolean(b.pinned)) return a.pinned ? -1 : 1;
  const ta = a.updatedAt ? Date.parse(a.updatedAt) : 0;
  const tb = b.updatedAt ? Date.parse(b.updatedAt) : 0;
  return tb - ta;
}

const GROUP_ORDER: SessionGroupKey[] = [
  "pinned",
  "today",
  "yesterday",
  "week",
  "month",
  "older",
];

const formatterCache = new Map<string, Intl.DateTimeFormat>();

/** 时间戳在指定时区下的「日序号」（自纪元起的天数），供跨时区稳定的日界比较。 */
function dayOrdinal(ts: number, timeZone?: string): number {
  const cacheKey = timeZone ?? "local";
  let formatter = formatterCache.get(cacheKey);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    formatterCache.set(cacheKey, formatter);
  }
  const parts = formatter.formatToParts(new Date(ts));
  const value = (type: string) =>
    Number(parts.find((part) => part.type === type)?.value ?? 0);
  return Date.UTC(value("year"), value("month") - 1, value("day")) / DAY_MS;
}

function bucketKey(deltaDays: number): SessionGroupKey {
  if (deltaDays <= 0) return "today";
  if (deltaDays === 1) return "yesterday";
  if (deltaDays <= 6) return "week";
  if (deltaDays <= 29) return "month";
  return "older";
}

/**
 * 把排好序的会话切成时间分组。输入顺序在各组内保持不变；
 * 空组不输出；置顶会话独立成组（要求输入已按 sortSessionsForDisplay 排序）；
 * 无更新时间的会话归入「更早」。
 */
export function groupSessionsByRecency(
  sessions: Session[],
  timeZone?: string,
  now: number = Date.now(),
): SessionGroup[] {
  const today = dayOrdinal(now, timeZone);
  const buckets = new Map<SessionGroupKey, Session[]>();
  for (const session of sessions) {
    let key: SessionGroupKey;
    if (session.pinned) {
      key = "pinned";
    } else {
      const ts = session.updatedAt ? Date.parse(session.updatedAt) : Number.NaN;
      key = Number.isNaN(ts)
        ? "older"
        : bucketKey(today - dayOrdinal(ts, timeZone));
    }
    const bucket = buckets.get(key);
    if (bucket) bucket.push(session);
    else buckets.set(key, [session]);
  }
  return GROUP_ORDER.filter((key) => buckets.has(key)).map((key) => ({
    key,
    sessions: buckets.get(key) as Session[],
  }));
}
