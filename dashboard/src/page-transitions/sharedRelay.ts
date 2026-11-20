import type { ResolvedRoute } from "./types";

/**
 * 共享元素接力判定。
 *
 * 页面在路由声明里只写「能承接哪些共享元素」（如 thread-title），
 * 实际记录的是具体 id（如 thread-title:初次问候）。
 * 只有来源页与目标页都声明了同一种能力、且确实有未过期的记录时才接力。
 */
export function resolveSharedRelay(
  from: ResolvedRoute | null,
  to: ResolvedRoute,
  pendingIds: readonly string[],
): boolean {
  if (!from || from.stage === to.stage) return false;
  const fromCaps = new Set(from.spec.shared ?? []);
  const common = (to.spec.shared ?? []).filter((cap) => fromCaps.has(cap));
  if (!common.length) return false;
  return pendingIds.some((id) =>
    common.some((cap) => id === cap || id.startsWith(`${cap}:`)),
  );
}
