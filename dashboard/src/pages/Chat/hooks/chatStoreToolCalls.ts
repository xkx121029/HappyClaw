/**
 * Tool-call bubbles: index/call-id resolution, upsert, result extraction and closing.
 */

import { generateId } from "../../../utils/messageParser";
import { type SessionStreamState } from "./sseHelpers";
import { type ToolCallChunk } from "../../../utils/parseHarnessChunk";
import { parseToolExecutionFeedback } from "../../../utils/toolMediaBlocks";
import { sameStreamingSpeaker } from "../utils/messageGrouping";
import {
  mergePatchedToolOutput,
} from "../../../plugins/toolRenderers/parseToolOutput";
import { promoteAskUserToolMessage } from "../utils/pendingHitl";
import { emitToolEvent } from "./chatStoreEvents";
import { sessionStates } from "./chatStoreState";
import { notify } from "./chatStorePublish";
import { getFocusedChatSession } from "./chatStoreFocus";
import { sessionHostAgentId } from "./chatStoreSocket";
import { sealPriorStreamingAssistants } from "./chatStoreMessageBubbles";

export /** Start or update a tool-call bubble. Prefer harness ``id`` over ``index`` so
 *  parallel tool calls do not share name/args. */
function toolIndexKey(index: number | undefined): string {
  return `idx-${index ?? 0}`;
}

export function speakerToolKey(speaker: string | undefined, key: string): string {
  const prefix = (speaker || "").trim();
  return prefix ? `${prefix}::${key}` : key;
}

export function resolveToolMessageId(
  state: SessionStreamState,
  chunk: ToolCallChunk,
  speaker?: string,
): string | undefined {
  const id = chunk.id?.trim() || undefined;
  if (id) {
    const byId = state.toolCallIdIndex[speakerToolKey(speaker, id)];
    if (byId) return byId;
  }

  const indexKey = speakerToolKey(speaker, toolIndexKey(chunk.index));
  const byIndex = state.toolCallIdIndex[indexKey];
  if (!byIndex) return undefined;

  if (id) {
    const existing = state.messages.find((m) => m.id === byIndex);
    const bound = existing?.toolData?.callId;
    if (bound && bound !== id && !bound.startsWith("idx-")) {
      return undefined;
    }
  }
  return byIndex;
}

export function registerToolCallKeys(
  state: SessionStreamState,
  msgId: string,
  chunk: ToolCallChunk,
  speaker?: string,
): void {
  const id = chunk.id?.trim() || undefined;
  const indexKey = speakerToolKey(speaker, toolIndexKey(chunk.index));
  state.toolCallIdIndex[indexKey] = msgId;
  if (id) state.toolCallIdIndex[speakerToolKey(speaker, id)] = msgId;
}

export function unregisterToolCallKeys(
  state: SessionStreamState,
  msgId: string,
): void {
  for (const [key, value] of Object.entries(state.toolCallIdIndex)) {
    if (value === msgId) delete state.toolCallIdIndex[key];
  }
}

export function extractToolCallIdFromResult(messages: unknown[]): string | undefined {
  for (const raw of messages) {
    if (!raw || typeof raw !== "object") continue;
    const obj = raw as Record<string, unknown>;
    const tid = obj.tool_call_id ?? obj.toolCallId;
    if (typeof tid === "string" && tid.trim()) return tid.trim();
  }
  return undefined;
}

export function upsertToolCall(
  state: SessionStreamState,
  chunk: ToolCallChunk,
  sessionId?: string,
  speaker?: string,
): void {
  const id = chunk.id?.trim() || undefined;
  const indexKey = toolIndexKey(chunk.index);
  const callId = id ?? indexKey;
  const existingMsgId = resolveToolMessageId(state, chunk, speaker);
  if (existingMsgId) {
    const idx = state.messages.findIndex((m) => m.id === existingMsgId);
    if (idx >= 0) {
      const m = state.messages[idx];
      const prevArgs = m.toolData?.arguments ?? "";
      const nextArgs = prevArgs + (chunk.args ?? "");
      const nextName = chunk.name || m.toolData?.name;
      const nextDisplay = chunk.display_name || m.toolData?.displayName;
      const nextCallId =
        m.toolData?.callId?.startsWith("idx-") && id
          ? id
          : m.toolData?.callId ?? callId;
      state.messages = [
        ...state.messages.slice(0, idx),
        promoteAskUserToolMessage({
          ...m,
          speakerAgentId: speaker ?? m.speakerAgentId,
          toolData: {
            ...(m.toolData ?? {}),
            name: nextName,
            displayName: nextDisplay,
            callId: nextCallId,
            arguments: nextArgs,
          },
        }),
        ...state.messages.slice(idx + 1),
      ];
      registerToolCallKeys(state, existingMsgId, chunk, speaker);
    }
    return;
  }
  sealPriorStreamingAssistants(state, speaker);
  const msgId = generateId();
  registerToolCallKeys(state, msgId, chunk, speaker);
  state.messages = [
    ...state.messages,
    promoteAskUserToolMessage({
      id: msgId,
      role: "assistant",
      content: "",
      toolData: {
        name: chunk.name,
        displayName: chunk.display_name,
        callId,
        arguments: chunk.args ?? "",
      },
      status: "streaming",
      timestamp: Date.now(),
      speakerAgentId: speaker,
    }),
  ];
  emitToolEvent({
    kind: "toolStart",
    sessionId: sessionId ?? "",
    toolName: chunk.name ?? "",
    toolId: callId,
  });
}

export /** Close the tool bubble that matches ``tool_call_id`` in the result, or the
 *  most recently opened streaming tool bubble as a fallback. */
function extractToolResultOutput(messages: unknown[]): string {
  const mediaTypes = new Set(["image", "file", "audio", "video"]);
  for (const raw of messages) {
    if (!raw || typeof raw !== "object") continue;
    const obj = raw as Record<string, unknown>;
    const content = obj.content;

    if (Array.isArray(content)) {
      const hasMedia = content.some(
        (part) =>
          part &&
          typeof part === "object" &&
          mediaTypes.has(String((part as Record<string, unknown>).type || "")),
      );
      if (hasMedia) {
        return JSON.stringify(content);
      }
      const textParts: string[] = [];
      for (const part of content) {
        if (
          part &&
          typeof part === "object" &&
          typeof (part as Record<string, unknown>).text === "string"
        ) {
          textParts.push(String((part as Record<string, unknown>).text));
        }
      }
      if (textParts.length > 0) {
        return textParts.join("\n");
      }
      // Non-text structured blocks (rare) — keep JSON for UI parsers.
      if (content.length > 0) {
        return JSON.stringify(content);
      }
      continue;
    }

    // Already-parsed JSON object (e.g. octop_ui envelope) — must not drop.
    if (content && typeof content === "object") {
      return JSON.stringify(content);
    }

    if (typeof content === "string" && content) {
      return content;
    }

    // Some runtimes put the payload on ``output`` / ``artifact`` instead.
    for (const key of ["output", "artifact", "result"] as const) {
      const v = obj[key];
      if (typeof v === "string" && v) return v;
      if (v && typeof v === "object") return JSON.stringify(v);
    }
  }
  return "";
}

export /** First non-null ToolMessage ``artifact`` in a tool_result frame, if any. */
function extractToolResultArtifact(messages: unknown[]): unknown {
  for (const raw of messages) {
    if (!raw || typeof raw !== "object") continue;
    const artifact = (raw as Record<string, unknown>).artifact;
    if (artifact !== undefined && artifact !== null) return artifact;
  }
  return undefined;
}

export function closeToolCall(
  state: SessionStreamState,
  messages: unknown[],
  sessionId?: string,
  speaker?: string,
): void {
  const toolCallId = extractToolCallIdFromResult(messages);
  let toolIdx = -1;

  if (toolCallId) {
    const mapped =
      state.toolCallIdIndex[speakerToolKey(speaker, toolCallId)] ??
      state.toolCallIdIndex[toolCallId];
    if (mapped) {
      toolIdx = state.messages.findIndex((m) => m.id === mapped);
    }
    if (toolIdx < 0) {
      for (let i = state.messages.length - 1; i >= 0; i--) {
        const m = state.messages[i];
        if (
          m.role === "assistant" &&
          m.toolData?.callId === toolCallId &&
          m.status === "streaming" &&
          sameStreamingSpeaker(
            m.speakerAgentId,
            speaker,
            sessionHostAgentId(state, sessionId),
            Boolean(state.isTeamRoom),
          )
        ) {
          toolIdx = i;
          break;
        }
      }
    }
  }

  if (toolIdx < 0) {
    for (let i = state.messages.length - 1; i >= 0; i--) {
      const m = state.messages[i];
      if (
        m.role === "assistant" &&
        m.toolData &&
        m.status === "streaming" &&
        sameStreamingSpeaker(
          m.speakerAgentId,
          speaker,
          sessionHostAgentId(state, sessionId),
          Boolean(state.isTeamRoom),
        )
      ) {
        toolIdx = i;
        break;
      }
    }
  }
  if (toolIdx < 0) return;
  const target = state.messages[toolIdx];
  const output = extractToolResultOutput(messages);
  const artifact = extractToolResultArtifact(messages);
  const explicitToolError = messages.some(
    (raw) =>
      raw !== null &&
      typeof raw === "object" &&
      (raw as Record<string, unknown>).status === "error",
  );
  const feedback = parseToolExecutionFeedback(output);
  const isToolError = explicitToolError || feedback?.isError === true;
  const errorCode = feedback?.code || (isToolError ? "tool_error" : undefined);
  state.messages = [
    ...state.messages.slice(0, toolIdx),
    {
      ...target,
      status: isToolError ? "error" : "done",
      errorInfo: isToolError
        ? {
            message: feedback?.message || output,
            code: errorCode,
            source: "tool_result",
            retryable: feedback?.retryable,
          }
        : undefined,
      toolData: {
        ...(target.toolData ?? {}),
        output,
        errorCode,
        ...(artifact != null ? { artifact } : {}),
      },
    },
    ...state.messages.slice(toolIdx + 1),
  ];
  unregisterToolCallKeys(state, target.id);
  if ((target.toolData?.name || "") === "ask_agent") {
    sealPriorStreamingAssistants(state, speaker);
  }
  emitToolEvent({
    kind: "toolDone",
    sessionId: sessionId ?? "",
    toolName: target.toolData?.name ?? "",
    toolId: target.toolData?.callId ?? "",
  });
}

/**
 * L2 interactive update: rewrite the tool bubble ``output`` for ``callId``
 * (merges into ``octop_ui`` JSON ``data`` when present). Searches the focused
 * session first, then any live session that owns the call id.
 */
export function patchToolResultData(callId: string, nextData: unknown): void {
  if (!callId) return;

  const tryPatch = (sessionId: string): boolean => {
    const state = sessionStates.get(sessionId);
    if (!state) return false;
    const mapped = state.toolCallIdIndex[callId];
    let idx = mapped ? state.messages.findIndex((m) => m.id === mapped) : -1;
    if (idx < 0) {
      idx = state.messages.findIndex(
        (m) => m.toolData?.callId === callId && !!m.toolData,
      );
    }
    if (idx < 0) return false;
    const target = state.messages[idx];
    const output = mergePatchedToolOutput(target.toolData?.output, nextData);
    state.messages = [
      ...state.messages.slice(0, idx),
      {
        ...target,
        toolData: {
          ...(target.toolData ?? {}),
          output,
        },
      },
      ...state.messages.slice(idx + 1),
    ];
    notify(state);
    return true;
  };

  const focused = getFocusedChatSession();
  if (focused && tryPatch(focused)) return;
  for (const sessionId of sessionStates.keys()) {
    if (tryPatch(sessionId)) return;
  }
}
