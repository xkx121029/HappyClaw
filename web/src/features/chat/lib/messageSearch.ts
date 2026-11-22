import type { ChatMessage } from "../hooks/useChat";

/** 一条命中：消息 id + 该消息内第几次出现（从 0 开始）。 */
export interface MessageSearchHit {
  messageId: string;
  occurrence: number;
}

/** 命中上限：超长会话里只统计前 500 处，够用且不拖慢逐字输入。 */
export const MAX_MESSAGE_SEARCH_HITS = 500;

export function normalizeSearchQuery(query: string): string {
  return query.trim().toLowerCase();
}

/** 只搜人读的正文；工具与系统消息是机器产出的，高亮它们只会制造噪音。 */
function isSearchable(message: ChatMessage): boolean {
  return message.role === "user" || message.role === "assistant";
}

/**
 * 在已加载的消息里做大小写不敏感的全量查找。
 * 返回顺序即文档顺序，供顶部计数与上下切换使用。
 */
export function findMessageHits(
  messages: readonly ChatMessage[],
  query: string,
): MessageSearchHit[] {
  const needle = normalizeSearchQuery(query);
  if (!needle) return [];

  const hits: MessageSearchHit[] = [];
  for (const message of messages) {
    if (!isSearchable(message)) continue;
    const text = (message.content ?? "").toLowerCase();
    if (!text) continue;

    let from = 0;
    let occurrence = 0;
    while (from <= text.length - needle.length) {
      const at = text.indexOf(needle, from);
      if (at < 0) break;
      hits.push({ messageId: message.id, occurrence });
      occurrence += 1;
      if (hits.length >= MAX_MESSAGE_SEARCH_HITS) return hits;
      from = at + needle.length;
    }
  }
  return hits;
}
