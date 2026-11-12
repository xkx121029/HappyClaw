/**
 * 会话导出：把当前消息列表拼成一份 Markdown 文本并触发浏览器下载。
 * 纯函数无 i18n 依赖 —— 文案由调用方传入，便于单测。
 */
import type { ChatMessage } from "../hooks/sseHelpers";

export interface TranscriptLabels {
  user: string;
  assistant: string;
  failed: string;
}

export interface TranscriptLine {
  speaker: string;
  time: string;
  text: string;
  /** 失败气泡的提示文案；空串表示未失败。 */
  failedNote: string;
}

/** 取气泡的展示正文：优先文本块（跳过 thinking），回退到 content。 */
export function messageExportText(message: ChatMessage): string {
  const blocks = message.contentBlocks;
  if (blocks?.length) {
    const text = blocks
      .filter((block) => block.type === "text")
      .map((block) => (block.content ?? "").trim())
      .filter(Boolean)
      .join("\n\n")
      .trim();
    if (text) return text;
  }
  return (message.content ?? "").trim();
}

/** 消息列表 → 导出行；跳过 system/tool 与无正文的消息。 */
export function buildTranscriptLines(
  messages: ChatMessage[],
  labels: TranscriptLabels,
  formatTime: (ts: number) => string,
): TranscriptLine[] {
  const lines: TranscriptLine[] = [];
  for (const message of messages) {
    if (message.role !== "user" && message.role !== "assistant") continue;
    const text = messageExportText(message);
    if (!text) continue;
    lines.push({
      speaker: message.role === "user" ? labels.user : labels.assistant,
      time: formatTime(message.timestamp),
      text,
      failedNote: message.status === "error" ? labels.failed : "",
    });
  }
  return lines;
}

/** 行数组 → Markdown 文本。标题一级，导出时间引用块，条目间水平线。 */
export function buildTranscriptMarkdown(
  title: string,
  lines: TranscriptLine[],
  exportedAtLabel?: string,
): string {
  const parts: string[] = [`# ${title}`];
  if (exportedAtLabel) parts.push(`> ${exportedAtLabel}`);
  for (const line of lines) {
    const head = line.time
      ? `**${line.speaker}** · ${line.time}`
      : `**${line.speaker}**`;
    const body = line.failedNote
      ? `${line.text}\n\n> ${line.failedNote}`
      : line.text;
    parts.push(`${head}\n\n${body}`);
  }
  return parts.join("\n\n---\n\n") + "\n";
}

/** 文件名清洗：去掉平台非法字符与控制字符、首尾点空格，限长 80，空标题回退。 */
export function sanitizeTranscriptFileName(
  title: string,
  fallback: string,
): string {
  const cleaned = (title ?? "")
    .replace(/[\\/:*?"<>|]/g, " ")
    .split("")
    .filter((ch) => ch.charCodeAt(0) >= 32)
    .join("")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^[.\s]+|[.\s]+$/g, "")
    .slice(0, 80)
    .replace(/[.\s]+$/g, "");
  return cleaned || fallback;
}

/** 触发浏览器下载一个 UTF-8 文本文件。 */
export function downloadTextFile(fileName: string, text: string): void {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}
