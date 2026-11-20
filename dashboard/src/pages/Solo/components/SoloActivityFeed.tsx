import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  FileCode2,
  Globe2,
  Loader2,
  SquareTerminal,
  Wrench,
} from "lucide-react";
import cx from "classnames";
import type { ChatMessage } from "../../Chat/hooks/sseHelpers";
import {
  collectToolMediaFromToolData,
  type ToolMediaItem,
} from "../../../utils/toolMediaBlocks";
import { ToolMediaStrip } from "../../Chat/components/ToolMediaStrip";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import {
  formatServerHourMinute,
  formatServerYmd,
} from "../../../utils/formatMessageTime";
import styles from "../solo.module.less";

export type ActionTargetKind = "file" | "command" | "browser" | "other";

/**
 * ANSI 转义序列。用 `String.fromCharCode(27)` 拼出来，避免把裸 ESC 写进源码
 * （ESLint `no-control-regex` 会报错，编辑器也会当成乱码）。
 */
const ANSI_ESCAPE = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g");

export interface DiffLine {
  type: "add" | "del" | "context";
  text: string;
}

/** 文件改动的行数统计（优先取工具输出里的 diff，其次按参数估算）。 */
export interface ActionDiffStat {
  added: number;
  removed: number;
  /** 首条变更内容，单行，用来判断改了什么。 */
  preview: string;
  /** 只读 diff 内容，供抽屉展示。 */
  lines: DiffLine[];
}

export interface SoloActivityItem {
  id: string;
  kind: "user" | "assistant" | "tool";
  /** 工具名（或「你」「专家」）。 */
  title: string;
  /** 目标：文件路径、命令或网址。 */
  target: string;
  targetKind: ActionTargetKind;
  /** 参数里出现的文件路径，可直接在编辑器打开。 */
  filePaths: string[];
  /** 结果摘要（首行，短）。 */
  summary: string;
  /** 完整结果 / 错误输出。 */
  body: string;
  running: boolean;
  failed: boolean;
  timestamp: number;
  /** 命令退出码；只在确实是命令类工具时给值。 */
  exitCode: number | null;
  /** 文件改动摘要；只在有改动时给值。 */
  diff: ActionDiffStat | null;
  images: ToolMediaItem[];
  videos: ToolMediaItem[];
  files: Array<{ url: string; filename?: string }>;
}

const BODY_LIMIT = 6000;
const FILE_KEYS = [
  "file_path",
  "filePath",
  "path",
  "notebook_path",
  "target_path",
  "new_path",
  "source_path",
  "destination",
  "filename",
];
const COMMAND_KEYS = ["command", "cmd", "script", "shell_command"];
const BROWSER_KEYS = ["url", "urls", "href", "page_url"];

function compact(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return "";
}

function parseArgs(raw?: string): Record<string, unknown> | null {
  if (!raw?.trim()) return null;
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // 工具参数偶尔是半截 JSON（流式过程中），按纯文本处理。
  }
  return null;
}

function pick(obj: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = compact(obj[key]);
    if (value && value !== "[object Object]") return value;
  }
  return "";
}

/** 从参数里收集看起来像工作区文件路径的字符串。 */
export function extractFilePaths(raw?: string): string[] {
  const obj = parseArgs(raw);
  if (!obj) return [];
  const paths: string[] = [];
  for (const key of FILE_KEYS) {
    const value = obj[key];
    if (typeof value === "string" && value.trim()) paths.push(value.trim());
  }
  for (const key of ["paths", "files"]) {
    const value = obj[key];
    if (Array.isArray(value)) {
      for (const entry of value) {
        if (typeof entry === "string" && entry.trim()) paths.push(entry.trim());
      }
    }
  }
  return [...new Set(paths)].slice(0, 4);
}

/** 判断动作类型并取出目标，优先按工具语义取对应字段。 */
export function describeToolTarget(
  name: string,
  raw?: string,
): { target: string; targetKind: ActionTargetKind } {
  const args = parseArgs(raw);
  if (!args) return { target: "", targetKind: "other" };

  if (/browser|playwright|chrome|puppeteer|navigate|screenshot|page/i.test(name)) {
    return { target: pick(args, BROWSER_KEYS), targetKind: "browser" };
  }
  if (/shell|terminal|exec|bash|command|^run|run_/i.test(name)) {
    return {
      target: pick(args, COMMAND_KEYS),
      targetKind: "command",
    };
  }
  if (/file|write|read|edit|patch|apply|glob|grep|replace|workspace/i.test(name)) {
    return { target: pick(args, FILE_KEYS), targetKind: "file" };
  }

  const target =
    pick(args, BROWSER_KEYS) ||
    pick(args, COMMAND_KEYS) ||
    pick(args, FILE_KEYS) ||
    pick(args, ["query", "selector", "text", "action"]);
  return { target, targetKind: target ? "other" : "other" };
}

/** 结果摘要：去掉 ANSI 控制符，取第一行有内容的文本。 */
export function summarizeToolOutput(output?: string): string {
  if (!output) return "";
  const clean = output.replace(ANSI_ESCAPE, "").trim();
  if (!clean) return "";
  const line = clean.split(/\r?\n/).find((item) => item.trim()) ?? "";
  return line.trim().slice(0, 160);
}

/** 命令输出只保留尾部若干行：日志再长也只在时间线里留结论。 */
export function tailOutput(output: string | undefined, maxLines = 40): string {
  if (!output) return "";
  const clean = output
    .replace(ANSI_ESCAPE, "")
    .replace(/\r\n/g, "\n")
    .trimEnd();
  const lines = clean.split("\n");
  if (lines.length <= maxLines) return clean;
  const omitted = lines.length - maxLines;
  return `…（前面 ${omitted} 行已省略）\n${lines.slice(-maxLines).join("\n")}`;
}

/** 命令摘要取输出结尾：退出前的结论通常落在最后一行。 */
export function summarizeCommandTail(output?: string): string {
  if (!output) return "";
  const lines = output
    .replace(ANSI_ESCAPE, "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return (lines[lines.length - 1] ?? "").slice(0, 160);
}

/** 从输出里读退出码，兼容 `exit code: 1` / `Exit status 2` / `[exit 127]`。 */
export function extractExitCode(output?: string): number | null {
  if (!output) return null;
  const match = output.match(
    /\bexit(?:\s*code|\s*status)?\s*[:=]?\s*(-?\d{1,3})\b/i,
  );
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) ? value : null;
}

const DIFF_OLD_KEYS = [
  "old_string",
  "old_str",
  "oldText",
  "old_text",
  "original",
  "old_content",
];
const DIFF_NEW_KEYS = [
  "new_string",
  "new_str",
  "newText",
  "new_text",
  "replacement",
  "new_content",
  "content",
];

const MAX_DIFF_LINES = 400;

/** 解析 unified diff / patch 文本，保留新增、删除与上下文行。 */
function parseUnifiedDiff(text: string): DiffLine[] {
  const lines: DiffLine[] = [];
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    if (
      raw.startsWith("diff --git ") ||
      raw.startsWith("index ") ||
      raw.startsWith("new file mode") ||
      raw.startsWith("deleted file mode") ||
      raw.startsWith("similarity index") ||
      raw.startsWith("rename from") ||
      raw.startsWith("rename to") ||
      raw.startsWith("--- ") ||
      raw.startsWith("+++ ") ||
      raw.startsWith("***") ||
      raw.startsWith("\\ No newline")
    ) {
      continue;
    }
    if (raw.startsWith("@@")) {
      lines.push({ type: "context", text: raw });
      continue;
    }
    if (raw.startsWith("+")) {
      lines.push({ type: "add", text: raw.slice(1) });
      continue;
    }
    if (raw.startsWith("-")) {
      lines.push({ type: "del", text: raw.slice(1) });
      continue;
    }
    if (raw.startsWith(" ")) {
      lines.push({ type: "context", text: raw.slice(1) });
    }
    if (lines.length >= MAX_DIFF_LINES) break;
  }
  return lines;
}

function splitDiffText(text: string): string[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  while (lines.length > 0 && !lines[0].trim()) lines.shift();
  while (lines.length > 0 && !lines[lines.length - 1].trim()) lines.pop();
  return lines;
}

/**
 * 生成只读 diff：优先用输出里的 unified diff，其次 patch，最后按
 * old/new 参数拼出删除行与新增行。绝不写入磁盘，只用于查看。
 */
export function extractDiffLines(
  args: Record<string, unknown> | null,
  output?: string,
): DiffLine[] {
  if (output && /^(diff --git |--- |\+\+\+ |@@ )/m.test(output)) {
    const fromOutput = parseUnifiedDiff(output);
    if (fromOutput.length > 0) return fromOutput;
  }
  if (!args) return [];
  const patch = pick(args, ["patch", "diff"]);
  if (patch && /(\*\*\* Begin Patch|^diff --git |^--- |^@@ )/m.test(patch)) {
    const fromPatch = parseUnifiedDiff(patch);
    if (fromPatch.length > 0) return fromPatch;
  }
  const oldText = pick(args, DIFF_OLD_KEYS);
  const newText = pick(args, DIFF_NEW_KEYS);
  if (!oldText && !newText) return [];
  const lines: DiffLine[] = [
    ...splitDiffText(oldText).map(
      (text): DiffLine => ({ type: "del", text }),
    ),
    ...splitDiffText(newText).map(
      (text): DiffLine => ({ type: "add", text }),
    ),
  ];
  return lines.slice(0, MAX_DIFF_LINES);
}

/**
 * 文件改动摘要：先看工具输出里有没有真实 diff，没有再按参数里的
 * old/new 文本估算，保证写文件类动作也能给出 `+N −M` 与首条变更。
 */
export function extractDiffStat(
  args: Record<string, unknown> | null,
  output?: string,
): ActionDiffStat | null {
  const lines = extractDiffLines(args, output);
  if (lines.length === 0) return null;
  let added = 0;
  let removed = 0;
  let preview = "";
  for (const line of lines) {
    if (line.type === "add") {
      added += 1;
      if (!preview && line.text.trim()) preview = line.text.trim();
    } else if (line.type === "del") {
      removed += 1;
    }
  }
  if (!added && !removed) return null;
  return { added, removed, preview: preview.slice(0, 120), lines };
}

/**
 * 把对话消息整理成「AI 行动时间线」。
 *
 * 工具调用保留时间、工具名、目标、状态与结果摘要；用户消息和专家回复
 * 作为分隔节点。数据全部来自当前会话消息（WS 实时推送 + 历史回放），
 * 因此切换会话或刷新后记录仍然存在。
 */
export function buildSoloActivity(
  messages: ChatMessage[],
  agentId: string | null | undefined,
  labels: { user: string; expert: string; tool: string },
  max = 120,
): SoloActivityItem[] {
  const items: SoloActivityItem[] = [];
  const empty = {
    images: [] as ToolMediaItem[],
    videos: [] as ToolMediaItem[],
    files: [] as Array<{ url: string; filename?: string }>,
    exitCode: null,
    diff: null,
  };

  for (const message of messages) {
    const tool = message.toolData;
    if (tool && (tool.name || tool.displayName || tool.output || tool.arguments)) {
      const media = collectToolMediaFromToolData(
        tool,
        agentId ?? null,
        message.attachments,
      );
      const output = tool.output ?? "";
      const name = tool.displayName || tool.name || labels.tool;
      const args = parseArgs(tool.arguments);
      const { target, targetKind } = describeToolTarget(
        tool.name || tool.displayName || "",
        tool.arguments,
      );
      const isCommand = targetKind === "command";
      // 命令优先用事件里的 returnCode，其次从输出尾部兜底解析。
      const exitCode =
        typeof tool.returnCode === "number"
          ? tool.returnCode
          : isCommand
          ? extractExitCode(output)
          : null;
      const diff =
        targetKind === "file" ? extractDiffStat(args, output) : null;
      const failed =
        message.status === "error" ||
        Boolean(tool.errorCode) ||
        (exitCode !== null && exitCode !== 0);
      items.push({
        id: message.id,
        kind: "tool",
        title: name,
        target,
        targetKind,
        filePaths: extractFilePaths(tool.arguments),
        summary: isCommand
          ? summarizeCommandTail(output)
          : summarizeToolOutput(output),
        body: isCommand ? tailOutput(output) : output.slice(0, BODY_LIMIT),
        running: message.status === "streaming" && !output,
        failed,
        timestamp: message.timestamp,
        exitCode,
        diff,
        ...media,
      });
      continue;
    }

    const text = message.content?.trim();
    if (!text) continue;
    if (message.role === "user") {
      items.push({
        id: message.id,
        kind: "user",
        title: labels.user,
        target: "",
        targetKind: "other",
        filePaths: [],
        summary: text.replace(/\s+/g, " ").slice(0, 160),
        body: text.slice(0, BODY_LIMIT),
        running: false,
        failed: false,
        timestamp: message.timestamp,
        ...empty,
      });
      continue;
    }
    if (message.role === "assistant") {
      items.push({
        id: message.id,
        kind: "assistant",
        title: labels.expert,
        target: "",
        targetKind: "other",
        filePaths: [],
        summary: text.replace(/\s+/g, " ").slice(0, 160),
        body: text.slice(0, BODY_LIMIT),
        running: message.status === "streaming",
        failed: message.status === "error",
        timestamp: message.timestamp,
        ...empty,
      });
    }
  }

  return items.slice(-max);
}

function toolIcon(name: string, kind: ActionTargetKind) {
  if (kind === "browser") return <Globe2 size={13} />;
  if (kind === "command") return <SquareTerminal size={13} />;
  if (kind === "file") return <FileCode2 size={13} />;
  if (/browser|playwright|chrome|puppeteer|web|fetch/i.test(name)) {
    return <Globe2 size={13} />;
  }
  if (/shell|terminal|exec|bash|command|run/i.test(name)) {
    return <SquareTerminal size={13} />;
  }
  if (/file|workspace|patch|read|write|edit|glob|grep/i.test(name)) {
    return <FileCode2 size={13} />;
  }
  return <Wrench size={13} />;
}

function formatActionTime(timestamp: number, timeZone: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  const sameDay =
    formatServerYmd(date, timeZone) === formatServerYmd(new Date(), timeZone);
  return sameDay
    ? formatServerHourMinute(date, timeZone)
    : `${formatServerYmd(date, timeZone).slice(5)} ${formatServerHourMinute(
        date,
        timeZone,
      )}`;
}

interface SoloActivityFeedProps {
  items: SoloActivityItem[];
  agentId: string | null;
  isStreaming: boolean;
  onOpenFile: (path: string) => void;
  /** 打开只读 diff 抽屉；没有 diff 的动作不会触发。 */
  onInspectDiff: (item: SoloActivityItem) => void;
}

/** 中间栏顶部的 AI 行动时间线。 */
export default function SoloActivityFeed({
  items,
  agentId,
  isStreaming,
  onOpenFile,
  onInspectDiff,
}: SoloActivityFeedProps) {
  const { t } = useTranslation();
  const timeZone = useServerTimezone();
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [seenFailed, setSeenFailed] = useState<Set<string>>(new Set());

  const handleScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    stickRef.current =
      node.scrollHeight - node.scrollTop - node.clientHeight < 48;
  }, []);

  useEffect(() => {
    if (!stickRef.current) return;
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [items, isStreaming]);

  // 失败的动作默认展开，用户不用再点一次才能看到错误。
  const failedIds = useMemo(
    () => items.filter((item) => item.failed).map((item) => item.id),
    [items],
  );
  useEffect(() => {
    const fresh = failedIds.filter((id) => !seenFailed.has(id));
    if (fresh.length === 0) return;
    setSeenFailed((prev) => {
      const next = new Set(prev);
      fresh.forEach((id) => next.add(id));
      return next;
    });
    setExpanded((prev) => {
      const next = new Set(prev);
      fresh.forEach((id) => next.add(id));
      return next;
    });
  }, [failedIds, seenFailed]);

  const toggleExpanded = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  if (items.length === 0) {
    return (
      <div className={styles.activityEmpty}>
        {isStreaming ? (
          <Loader2 size={16} className={styles.spin} />
        ) : (
          <Activity size={16} />
        )}
        <p className={styles.activityEmptyTitle}>
          {isStreaming ? t("solo.activityStarting") : t("solo.activityEmpty")}
        </p>
        {!isStreaming ? (
          <p className={styles.activityEmptyHint}>
            {t("solo.activityEmptyHint")}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className={styles.activityScroll}
      ref={scrollRef}
      onScroll={handleScroll}
    >
      <ol className={styles.activityList}>
        {items.map((item) => {
          const hasBody = Boolean(item.body);
          const isOpen = expanded.has(item.id);
          const fileTarget =
            item.targetKind === "file" && item.target
              ? item.target
              : item.filePaths[0] ?? "";
          return (
            <li
              key={item.id}
              className={cx(
                styles.activityItem,
                item.kind === "user" && styles.activityItemUser,
                item.kind === "assistant" && styles.activityItemExpert,
                item.failed && styles.activityItemFailed,
              )}
            >
              <span className={styles.activityRailDot} aria-hidden />
              <div className={styles.activityCard}>
                <div className={styles.activityHead}>
                  <span className={styles.activityIcon}>
                    {item.kind === "tool"
                      ? toolIcon(item.title, item.targetKind)
                      : null}
                  </span>
                  <span className={styles.activityTitle} title={item.title}>
                    {item.title}
                  </span>
                  <span className={styles.activityTime}>
                    {formatActionTime(item.timestamp, timeZone)}
                  </span>
                  {item.running ? (
                    <span
                      className={cx(
                        styles.activityState,
                        styles.activityStateBusy,
                      )}
                    >
                      <Loader2 size={10} className={styles.spin} />
                      {t("solo.running")}
                    </span>
                  ) : item.failed ? (
                    <span
                      className={cx(
                        styles.activityState,
                        styles.activityStateFailed,
                      )}
                    >
                      <AlertTriangle size={10} />
                      {t("solo.failed")}
                    </span>
                  ) : item.kind === "tool" ? (
                    <span className={styles.activityState}>
                      <Check size={10} />
                      {t("solo.done")}
                    </span>
                  ) : null}
                </div>

                {item.target ? (
                  item.targetKind === "file" && fileTarget ? (
                    <button
                      type="button"
                      className={styles.activityTarget}
                      onClick={() => onOpenFile(fileTarget)}
                      title={t("solo.openInEditor")}
                    >
                      <FileCode2 size={11} />
                      <span>{item.target}</span>
                    </button>
                  ) : (
                    <button
                      type="button"
                      className={cx(
                        styles.activityTarget,
                        !hasBody && styles.activityTargetStatic,
                      )}
                      onClick={() => hasBody && toggleExpanded(item.id)}
                      title={
                        hasBody
                          ? t("solo.viewOutput")
                          : item.targetKind === "command"
                          ? t("solo.command")
                          : undefined
                      }
                    >
                      {item.targetKind === "command" ? (
                        <span className={styles.activityPrompt}>$</span>
                      ) : item.targetKind === "browser" ? (
                        <Globe2 size={11} />
                      ) : null}
                      <span>{item.target}</span>
                    </button>
                  )
                ) : null}

                {item.summary ? (
                  <div
                    className={cx(
                      styles.activitySummary,
                      item.failed && styles.activitySummaryFailed,
                    )}
                    title={item.summary}
                  >
                    {item.kind === "tool" ? "→ " : ""}
                    {item.summary}
                  </div>
                ) : null}

                {item.kind === "tool" && (item.exitCode !== null || item.diff) ? (
                  <div className={styles.activityMeta}>
                    {item.exitCode !== null ? (
                      <span
                        className={cx(
                          styles.activityChip,
                          item.exitCode !== 0 && styles.activityChipFail,
                        )}
                        title={t("solo.exitCode", { code: item.exitCode })}
                      >
                        {t("solo.exitCode", { code: item.exitCode })}
                      </span>
                    ) : null}
                    {item.diff ? (
                      <>
                        <span
                          className={cx(
                            styles.activityChip,
                            styles.activityChipAdd,
                          )}
                          title={t("solo.diffAdded", {
                            count: item.diff.added,
                          })}
                        >
                          +{item.diff.added}
                        </span>
                        <span
                          className={cx(
                            styles.activityChip,
                            styles.activityChipDel,
                          )}
                          title={t("solo.diffRemoved", {
                            count: item.diff.removed,
                          })}
                        >
                          −{item.diff.removed}
                        </span>
                        {item.diff.preview ? (
                          <span
                            className={styles.activityDiffPreview}
                            title={item.diff.preview}
                          >
                            {item.diff.preview}
                          </span>
                        ) : null}
                        {item.diff.lines.length > 0 ? (
                          <button
                            type="button"
                            className={styles.activityDiffOpen}
                            onClick={() => onInspectDiff(item)}
                          >
                            <FileCode2 size={11} />
                            {t("solo.viewDiff")}
                          </button>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                ) : null}

                {hasBody ? (
                  <>
                    {isOpen ? (
                      <pre className={styles.activityBody}>{item.body}</pre>
                    ) : null}
                    <button
                      type="button"
                      className={styles.activityExpand}
                      onClick={() => toggleExpanded(item.id)}
                    >
                      {isOpen ? (
                        <ChevronDown size={11} />
                      ) : (
                        <ChevronRight size={11} />
                      )}
                      {isOpen
                        ? t("solo.collapse")
                        : item.failed
                        ? t("solo.viewError")
                        : t("solo.viewOutput")}
                    </button>
                  </>
                ) : null}

                <div className={styles.activityMedia}>
                  <ToolMediaStrip
                    images={item.images}
                    videos={item.videos}
                    files={item.files}
                    agentId={agentId}
                  />
                </div>

                {item.filePaths.length > 1 ? (
                  <div className={styles.activityFiles}>
                    {item.filePaths.slice(1).map((path) => (
                      <button
                        type="button"
                        key={path}
                        className={styles.activityFileLink}
                        onClick={() => onOpenFile(path)}
                        title={path}
                      >
                        <FileCode2 size={10} />
                        {path}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
