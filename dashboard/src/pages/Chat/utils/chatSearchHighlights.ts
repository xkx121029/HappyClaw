const ALL_HIGHLIGHT = "octop-chat-search";
const ACTIVE_HIGHLIGHT = "octop-chat-search-active";

type HighlightCtor = new (...ranges: Range[]) => unknown;

interface HighlightRegistryLike {
  set(name: string, value: unknown): void;
  delete(name: string): void;
}

/** CSS Custom Highlight API 是唯一不会破坏 React 文本节点的做法。 */
function highlightApi(): {
  registry: HighlightRegistryLike;
  create: HighlightCtor;
} | null {
  const css = (globalThis as { CSS?: { highlights?: HighlightRegistryLike } })
    .CSS;
  const create = (globalThis as { Highlight?: HighlightCtor }).Highlight;
  if (!css?.highlights || !create) return null;
  return { registry: css.highlights, create };
}

export function supportsSearchHighlights(): boolean {
  return highlightApi() !== null;
}

export function clearSearchHighlights(): void {
  const api = highlightApi();
  if (!api) return;
  api.registry.delete(ALL_HIGHLIGHT);
  api.registry.delete(ACTIVE_HIGHLIGHT);
}

/** 按文档顺序收集某个消息容器内所有命中的 Range（虚拟列表复用时也沿用它）。 */
function collectOccurrenceRanges(
  container: HTMLElement,
  needle: string,
): Range[] {
  const ranges: Range[] = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    const text = node.nodeValue ?? "";
    if (text) {
      const lower = text.toLowerCase();
      let from = 0;
      while (from <= lower.length - needle.length) {
        const at = lower.indexOf(needle, from);
        if (at < 0) break;
        const range = document.createRange();
        range.setStart(node, at);
        range.setEnd(node, at + needle.length);
        ranges.push(range);
        from = at + needle.length;
      }
    }
    node = walker.nextNode();
  }
  return ranges;
}

function messageContainers(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>("[data-message-id]"));
}

/**
 * 给当前已渲染的消息打上高亮。虚拟列表只渲染可视区，
 * 所以每次滚动后调用方需要重新执行一次。
 */
export function applySearchHighlights(
  root: HTMLElement | null,
  query: string,
  activeMessageId: string | null,
  activeOccurrence: number,
): void {
  clearSearchHighlights();
  const api = highlightApi();
  const needle = query.trim().toLowerCase();
  if (!api || !root || !needle) return;

  const all: Range[] = [];
  const active: Range[] = [];
  for (const container of messageContainers(root)) {
    const isActive = container.dataset.messageId === activeMessageId;
    const ranges = collectOccurrenceRanges(container, needle);
    // 数据层按 content 计数，DOM 里 Markdown 会少掉个别字面量；
    // 索引越界时退到该消息最后一处，保证「当前命中」始终有可见落点。
    const activeIndex =
      isActive && activeOccurrence >= 0
        ? Math.min(activeOccurrence, ranges.length - 1)
        : -1;
    ranges.forEach((range, index) => {
      if (index === activeIndex) active.push(range);
      else all.push(range);
    });
  }

  if (all.length > 0) {
    api.registry.set(ALL_HIGHLIGHT, new api.create(...all));
  }
  if (active.length > 0) {
    api.registry.set(ACTIVE_HIGHLIGHT, new api.create(...active));
  }
}

/** 当前命中的屏幕位置；用于把第 n 处、而不是整条消息滚到视口中间。 */
export function findOccurrenceRect(
  root: HTMLElement | null,
  query: string,
  messageId: string | null,
  occurrence: number,
): DOMRect | null {
  const needle = query.trim().toLowerCase();
  if (!root || !messageId || !needle) return null;
  const container =
    root.querySelector<HTMLElement>(
      `[data-message-id="${CSS.escape(messageId)}"]`,
    ) ?? null;
  if (!container) return null;
  const ranges = collectOccurrenceRanges(container, needle);
  if (ranges.length === 0) return null;
  const index = Math.min(Math.max(occurrence, 0), ranges.length - 1);
  return ranges[index]?.getBoundingClientRect() ?? null;
}
