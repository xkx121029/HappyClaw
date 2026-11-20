/**
 * 共享元素：前后两个页面（或列表与详情）出现同一个元素时，
 * 让它在原位置和新位置之间做连续的平移 + 缩放，而不是整页淡入。
 *
 * 用法：
 *   1. 跳转/展开前：rememberSharedElement("job-123") 记录来源位置；
 *   2. 目标元素：<SharedElement id="job-123">…</SharedElement>，
 *      挂载时自动从记录的位置过渡到自己的位置；
 *   3. 返回时同理，反向再记录一次。
 *
 * 没记录到来源就不播放，绝不硬凑。
 */

export interface RectSnapshot {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface PendingEntry {
  rect: RectSnapshot;
  at: number;
}

const PENDING_TTL_MS = 2000;
const pending = new Map<string, PendingEntry>();

export function snapshotRect(rect: DOMRect): RectSnapshot {
  return {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
  };
}

export function rememberSharedRect(id: string, rect: RectSnapshot): void {
  if (!rect.width || !rect.height) return;
  pending.set(id, { rect, at: Date.now() });
}

/** 按 data-shared-id 记录来源；找不到或不可见时返回 false。 */
export function rememberSharedElement(
  id: string,
  root?: ParentNode | null,
): boolean {
  if (typeof document === "undefined") return false;
  const scope = root ?? document;
  const el = scope.querySelector<HTMLElement>(
    `[data-shared-id="${escapeAttribute(id)}"]`,
  );
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  if (!rect.width || !rect.height) return false;
  rememberSharedRect(id, snapshotRect(rect));
  return true;
}

/** 取出并清除记录；过期视为没有。 */
export function takeSharedRect(id: string): RectSnapshot | null {
  const entry = pending.get(id);
  if (!entry) return null;
  pending.delete(id);
  if (Date.now() - entry.at > PENDING_TTL_MS) return null;
  return entry.rect;
}

/**
 * 是否有共享元素正在衔接。用于决定页面转场是否退化为淡入：
 * 有共享元素时不做整页横向滑动，避免两种运动打架。
 */
export function hasPendingSharedElement(): boolean {
  const now = Date.now();
  for (const [id, entry] of pending) {
    if (now - entry.at > PENDING_TTL_MS) {
      pending.delete(id);
      continue;
    }
    return true;
  }
  return false;
}

export function clearSharedElements(): void {
  pending.clear();
}

/** 当前仍有效的共享元素记录 id，供转场库判断能否接力。 */
export function pendingSharedIds(): string[] {
  const now = Date.now();
  const ids: string[] = [];
  for (const [id, entry] of pending) {
    if (now - entry.at > PENDING_TTL_MS) {
      pending.delete(id);
      continue;
    }
    ids.push(id);
  }
  return ids;
}

function escapeAttribute(value: string): string {
  return value.replace(/["\\]/g, "\\$&");
}
