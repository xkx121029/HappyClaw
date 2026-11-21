import type { HistoryMessage } from "./types";

/** Message content is either a string or a list of content blocks. */
export function messageText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === "string") return block;
        if (typeof block === "object" && block !== null) {
          const row = block as { text?: unknown; content?: unknown; type?: unknown };
          if (typeof row.text === "string") return row.text;
          if (typeof row.content === "string") return row.content;
        }
        return "";
      })
      .filter(Boolean)
      .join("\n\n");
  }
  if (typeof content === "object" && content !== null) {
    const row = content as { text?: unknown };
    if (typeof row.text === "string") return row.text;
  }
  return "";
}

export function isUserMessage(message: HistoryMessage): boolean {
  return message.role === "user";
}

export function isAssistantMessage(message: HistoryMessage): boolean {
  return message.role === "assistant";
}
