import type { ChatMessage, DecisionNotice } from "../hooks/useChat";
import type { ThinkingProcessItem } from "./messageContent";
import { stripThinkTags } from "./messageContent";

/** One decision-model, thinking, or tool step inside an assistant turn. */
export type TurnStep =
  | { kind: "thinking"; id: string; item: ThinkingProcessItem }
  | { kind: "tool"; id: string; message: ChatMessage }
  | { kind: "decision"; id: string; notice: DecisionNotice };

/**
 * Ordered turn block. Assistant replies interleave narration and work:
 * text → tools/thinking → text → tools/thinking → text. Each run is its own
 * block so the transcript never glues two sentences together.
 */
export type TurnBlock =
  | { kind: "text"; id: string; message: ChatMessage }
  | { kind: "process"; id: string; steps: TurnStep[] }
  /** Rich plugin tool UI (chart, board…). Always visible, never folded away. */
  | { kind: "toolCard"; id: string; message: ChatMessage }
  | { kind: "hitl"; id: string; message: ChatMessage }
  | { kind: "error"; id: string; message: ChatMessage };

export type ProcessBlock = Extract<TurnBlock, { kind: "process" }>;

export interface PlannedProcessBlock {
  kind: "process";
  id: string;
  steps: TurnStep[];
  /**
   * True when earlier process runs were folded into one summary row
   * (「已执行 N 步，用时 Xs」) because a later text segment arrived.
   */
  merged: boolean;
  /** Wall-clock span of the folded runs. Null when history has no usable time. */
  durationMs: number | null;
  failedCount: number;
  live: boolean;
}

export type PlannedTurnBlock =
  | Exclude<TurnBlock, { kind: "process" }>
  | PlannedProcessBlock;

interface MessagePart {
  kind: "thinking" | "text";
  content: string;
  isStreaming: boolean;
}

/**
 * Split one stored message into its ordered visible parts. Older rows may keep
 * `[text, tool_use, text]` in one content array; walking blocks in order keeps
 * that interleaving instead of flattening it into one paragraph.
 */
function messageParts(message: ChatMessage): MessagePart[] {
  const streaming = message.status === "streaming";
  if (message.contentBlocks && message.contentBlocks.length > 0) {
    const parts: MessagePart[] = [];
    for (const block of message.contentBlocks) {
      if (block.type === "thinking") {
        const content = block.content.trim();
        if (content) {
          parts.push({ kind: "thinking", content, isStreaming: streaming });
        }
      } else if (block.type === "text") {
        const content = stripThinkTags(block.content);
        if (content)
          parts.push({ kind: "text", content, isStreaming: streaming });
      }
    }
    if (!parts.some((part) => part.kind === "text") && message.content) {
      const content = stripThinkTags(message.content);
      if (content)
        parts.push({ kind: "text", content, isStreaming: streaming });
    }
    return parts;
  }
  if (message.type === "reasoning" && message.content) {
    return [
      { kind: "thinking", content: message.content, isStreaming: streaming },
    ];
  }
  const content = message.content ? stripThinkTags(message.content) : "";
  return content ? [{ kind: "text", content, isStreaming: streaming }] : [];
}

export interface BuildTurnBlocksOptions {
  /** Rich plugin tool UIs render as first-class blocks instead of folded rows. */
  isPinnedTool?: (message: ChatMessage) => boolean;
}

export function buildTurnBlocks(
  messages: ChatMessage[],
  opts: BuildTurnBlocksOptions = {},
): TurnBlock[] {
  const blocks: TurnBlock[] = [];
  let open: ProcessBlock | null = null;

  const processBlock = (): ProcessBlock => {
    if (!open) {
      open = {
        kind: "process",
        id: `process-${messages[0]?.id ?? "turn"}-${blocks.length}`,
        steps: [],
      };
      blocks.push(open);
    }
    return open;
  };
  const closeProcess = () => {
    open = null;
  };

  for (const message of messages) {
    if (message.hitlData) {
      closeProcess();
      blocks.push({ kind: "hitl", id: `${message.id}:hitl`, message });
      continue;
    }

    if (message.decision) {
      processBlock().steps.push({
        kind: "decision",
        id: `${message.id}:decision`,
        notice: message.decision,
      });
    }

    if (message.status === "error" && !message.toolData) {
      closeProcess();
      blocks.push({ kind: "error", id: `${message.id}:error`, message });
      continue;
    }

    const parts = messageParts(message);
    const hasText = parts.some((part) => part.kind === "text");
    parts.forEach((part, index) => {
      if (part.kind === "thinking") {
        processBlock().steps.push({
          kind: "thinking",
          id: `${message.id}:thinking:${index}`,
          item: {
            messageId: message.id,
            content: part.content,
            // Same rule as the old fold: thinking stops looking live once its
            // message starts emitting visible text.
            isStreaming: part.isStreaming && !hasText,
          },
        });
        return;
      }
      closeProcess();
      const previous = blocks[blocks.length - 1];
      // Snapshot rows can repeat the same paragraph verbatim — keep one.
      if (
        previous?.kind === "text" &&
        previous.message.content === part.content
      ) {
        return;
      }
      blocks.push({
        kind: "text",
        id: `${message.id}:text:${index}`,
        message: {
          ...message,
          content: part.content,
          contentBlocks: undefined,
          toolData: undefined,
        },
      });
    });

    if (message.toolData) {
      if (opts.isPinnedTool?.(message)) {
        closeProcess();
        blocks.push({ kind: "toolCard", id: `${message.id}:card`, message });
      } else {
        processBlock().steps.push({
          kind: "tool",
          id: `${message.id}:tool`,
          message,
        });
      }
    }
  }

  return blocks;
}

export function isStepFailed(step: TurnStep): boolean {
  return (
    step.kind === "tool" &&
    (step.message.status === "error" ||
      Boolean(step.message.toolData?.errorCode))
  );
}

export function isStepRunning(step: TurnStep): boolean {
  if (step.kind === "tool") {
    return (
      step.message.status === "streaming" && !step.message.toolData?.output
    );
  }
  if (step.kind === "thinking") return Boolean(step.item.isStreaming);
  return false;
}

function countFailed(steps: TurnStep[]): number {
  return steps.filter(isStepFailed).length;
}

/**
 * Span between the earliest step timestamp and the text segment that closed
 * the run. Returns null when history carries no usable timestamps — never
 * invent a duration.
 */
function foldDuration(
  blocks: TurnBlock[],
  steps: TurnStep[],
  endIndex: number,
): number | null {
  const stamps: number[] = [];
  for (const step of steps) {
    if (step.kind === "tool" && step.message.timestamp > 0) {
      stamps.push(step.message.timestamp);
    }
  }
  const end = blocks[endIndex];
  if (end?.kind === "text" && end.message.timestamp > 0) {
    stamps.push(end.message.timestamp);
  }
  if (stamps.length < 2) return null;
  const span = Math.max(...stamps) - Math.min(...stamps);
  return span >= 1000 ? span : null;
}

function planned(
  block: ProcessBlock,
  merged: boolean,
  durationMs: number | null,
): PlannedProcessBlock {
  return {
    kind: "process",
    id: block.id,
    steps: block.steps,
    merged,
    durationMs,
    failedCount: countFailed(block.steps),
    live: block.steps.some(isStepRunning),
  };
}

/**
 * Fold process runs that precede the latest text segment into one group once
 * a second text segment exists. The group keeps its first position so it does
 * not jump around while the reply streams.
 */
export function planTurnBlocks(blocks: TurnBlock[]): PlannedTurnBlock[] {
  const textIndexes: number[] = [];
  blocks.forEach((block, index) => {
    if (block.kind === "text") textIndexes.push(index);
  });
  const lastText =
    textIndexes.length >= 2 ? textIndexes[textIndexes.length - 1] : -1;

  if (lastText < 0) {
    return blocks.map((block) =>
      block.kind === "process" ? planned(block, false, null) : block,
    );
  }

  const foldIndexes = blocks.reduce<number[]>((acc, block, index) => {
    if (block.kind === "process" && index < lastText) acc.push(index);
    return acc;
  }, []);
  if (foldIndexes.length === 0) {
    return blocks.map((block) =>
      block.kind === "process" ? planned(block, false, null) : block,
    );
  }

  const foldedSteps = foldIndexes.flatMap(
    (index) => (blocks[index] as ProcessBlock).steps,
  );
  const durationMs = foldDuration(blocks, foldedSteps, lastText);
  const failedCount = countFailed(foldedSteps);
  const firstFold = foldIndexes[0];

  const out: PlannedTurnBlock[] = [];
  blocks.forEach((block, index) => {
    if (block.kind !== "process") {
      out.push(block);
      return;
    }
    if (index < lastText) {
      if (index === firstFold) {
        out.push({
          kind: "process",
          id: `fold-${block.id}`,
          steps: foldedSteps,
          merged: true,
          durationMs,
          failedCount,
          live: false,
        });
      }
      return;
    }
    out.push(planned(block, false, null));
  });
  return out;
}

export function countSteps(steps: TurnStep[]): number {
  return steps.length;
}

/** `12s` / `3.4s` — matches the duration format used in message meta rows. */
export function formatStepDuration(durationMs: number): string {
  const seconds = durationMs / 1000;
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
}
