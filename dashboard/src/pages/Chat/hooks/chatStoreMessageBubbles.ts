/**
 * Assistant bubble assembly: streaming text/thinking fragments, turn ownership and bubble sealing.
 */

import { generateId } from "../../../utils/messageParser";
import { type ChatMessage, type SessionStreamState } from "./sseHelpers";
import {
  sealPriorStreamingAssistants as sealPriorStreamingAssistantsMessages,
} from "./sealPriorStreamingAssistants";
import {
  findSpeakerTextToContinue,
  isRoomHostSpeaker,
  sameStreamingSpeaker,
  speakerTurnWasInterrupted,
} from "../utils/messageGrouping";
import { sessionHostAgentId } from "./chatStoreSocket";

export function continueTokenOpts(state: SessionStreamState): {
  continueThroughTools?: string[];
  teamRoom: boolean;
} {
  const teamRoom = Boolean(state.isTeamRoom);
  return teamRoom
    ? { continueThroughTools: ["ask_agent"], teamRoom }
    : { teamRoom };
}

export /** Seal same-speaker streaming text/thinking before opening a new bubble. */
function sealPriorStreamingAssistants(
  state: SessionStreamState,
  speaker?: string,
): void {
  const next = sealPriorStreamingAssistantsMessages(
    state.messages,
    speaker,
    sessionHostAgentId(state),
    Boolean(state.isTeamRoom),
  );
  if (next !== state.messages) state.messages = next;
}

export function findWrapupTextToContinue(
  messages: ChatMessage[],
  speaker?: string,
  hostId?: string,
): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role === "user") break;
    if (message.role !== "assistant" || message.toolData) continue;
    if (!message.teamWrapup) continue;
    if (!sameStreamingSpeaker(message.speakerAgentId, speaker, hostId, true))
      continue;
    return i;
  }
  return -1;
}

export function appendToTextBubble(
  state: SessionStreamState,
  idx: number,
  content: string,
  forceStatus?: "done" | "streaming",
): void {
  const target = state.messages[idx];
  if (!target) return;
  const prev = target.content || "";
  if (prev && (content === prev || content.startsWith(prev))) {
    if (content === prev && !forceStatus) return;
    state.messages = [
      ...state.messages.slice(0, idx),
      {
        ...target,
        content,
        status: forceStatus ?? target.status,
      },
      ...state.messages.slice(idx + 1),
    ];
    return;
  }
  const nextContent = prev + content;
  const nextStatus =
    forceStatus ?? (target.status === "done" ? "streaming" : target.status);
  if (target.contentBlocks && target.contentBlocks.length > 0) {
    const blocks = [...target.contentBlocks];
    const lastBlock = blocks[blocks.length - 1];
    if (lastBlock.type === "text") {
      blocks[blocks.length - 1] = {
        ...lastBlock,
        content: lastBlock.content + content,
      };
    } else {
      blocks.push({ type: "text", content });
    }
    state.messages = [
      ...state.messages.slice(0, idx),
      {
        ...target,
        content: nextContent,
        contentBlocks: blocks,
        status: nextStatus,
      },
      ...state.messages.slice(idx + 1),
    ];
    return;
  }
  state.messages = [
    ...state.messages.slice(0, idx),
    { ...target, content: nextContent, status: nextStatus },
    ...state.messages.slice(idx + 1),
  ];
}

export function chunkTurnId(chunk: object): string {
  const raw = (chunk as { turn_id?: unknown }).turn_id;
  return typeof raw === "string" ? raw.trim() : "";
}

export /** A chunk with a turn id must not continue a bubble from another turn. */
function bubbleMatchesTurn(
  message: ChatMessage,
  turnId: string,
  activeTurnId: string | null | undefined,
): boolean {
  if (!turnId) return true;
  if (message.turnId) return message.turnId === turnId;
  if (message.status !== "streaming") return false;
  return !activeTurnId || activeTurnId === turnId;
}

export function noteTurnOwner(
  state: SessionStreamState,
  userId: number | undefined,
): void {
  if (userId != null && userId > 0) state.activeTurnUserId = userId;
}

export function noteTurnOwnerFromLatestUser(state: SessionStreamState): void {
  for (let i = state.messages.length - 1; i >= 0; i--) {
    const message = state.messages[i];
    if (message.role !== "user") continue;
    noteTurnOwner(state, message.author?.userId);
    return;
  }
}

export /** Append a token fragment to the last streaming assistant text bubble,
 *  starting a new bubble if the last message is something else. */
function appendStreamingToken(
  state: SessionStreamState,
  content: string,
  speakerAgentId?: string,
  snapshot = false,
  wrapup = false,
  keepLive = false,
  turnId = "",
): void {
  if (!content) return;
  const speaker = speakerAgentId?.trim() || undefined;
  const hostId = sessionHostAgentId(state);
  if (wrapup) {
    const wrapIdx = findWrapupTextToContinue(state.messages, speaker, hostId);
    if (wrapIdx >= 0) {
      appendToTextBubble(
        state,
        wrapIdx,
        content,
        snapshot ? "done" : undefined,
      );
      return;
    }
    sealPriorStreamingAssistants(state, speaker);
    state.streamId = generateId();
    state.messages = [
      ...state.messages,
      {
        id: state.streamId,
        role: "assistant",
        content,
        status: snapshot && !keepLive ? "done" : "streaming",
        timestamp: Date.now(),
        speakerAgentId: speaker,
        teamWrapup: true,
        ...(turnId ? { turnId } : {}),
      },
    ];
    return;
  }
  const idx = findSpeakerTextToContinue(
    state.messages,
    speaker,
    hostId,
    snapshot
      ? { teamRoom: Boolean(state.isTeamRoom) }
      : continueTokenOpts(state),
  );
  const found = idx >= 0 ? state.messages[idx] : null;
  if (found && !bubbleMatchesTurn(found, turnId, state.activeTurnId)) {
    sealPriorStreamingAssistants(state, speaker);
    state.streamId = generateId();
    state.messages = [
      ...state.messages,
      {
        id: state.streamId,
        role: "assistant",
        content,
        status: snapshot && !keepLive ? "done" : "streaming",
        timestamp: Date.now(),
        speakerAgentId: speaker,
        ...(turnId ? { turnId } : {}),
      },
    ];
    return;
  }
  if (found && turnId && !found.turnId) found.turnId = turnId;
  const target = found;
  if (snapshot && target) {
    const prev = target.content || "";
    const sameTurn =
      content === prev || content.startsWith(prev) || prev.startsWith(content);
    if (!sameTurn && target.status === "done") {
      sealPriorStreamingAssistants(state, speaker);
      state.messages = [
        ...state.messages,
        {
          id: generateId(),
          role: "assistant",
          content,
          status: keepLive ? "streaming" : "done",
          timestamp: Date.now(),
          speakerAgentId: speaker,
          ...(turnId ? { turnId } : {}),
        },
      ];
      return;
    }
    const next = sameTurn
      ? content.startsWith(prev) || content === prev
        ? content
        : prev
      : content;
    const snapStatus = keepLive ? "streaming" : "done";
    if (next !== prev || target.status !== snapStatus) {
      state.messages = [
        ...state.messages.slice(0, idx),
        { ...target, content: next, status: snapStatus },
        ...state.messages.slice(idx + 1),
      ];
    }
    return;
  }
  if (snapshot) {
    sealPriorStreamingAssistants(state, speaker);
    state.messages = [
      ...state.messages,
      {
        id: generateId(),
        role: "assistant",
        content,
        status: keepLive ? "streaming" : "done",
        timestamp: Date.now(),
        speakerAgentId: speaker,
        ...(turnId ? { turnId } : {}),
      },
    ];
    return;
  }
  const isHost = isRoomHostSpeaker(speaker, hostId);
  const interrupted =
    isHost &&
    target != null &&
    idx >= 0 &&
    speakerTurnWasInterrupted(
      state.messages,
      idx,
      speaker,
      hostId,
      Boolean(state.isTeamRoom),
    );
  // Members already on the wall — later host text is a new turn (wrap-up).
  if (target && interrupted) {
    sealPriorStreamingAssistants(state, speaker);
    state.streamId = generateId();
    state.messages = [
      ...state.messages,
      {
        id: state.streamId,
        role: "assistant",
        content,
        status: "streaming",
        timestamp: Date.now(),
        speakerAgentId: speaker,
        ...(turnId ? { turnId } : {}),
      },
    ];
    return;
  }
  if (target) {
    const prev = target.content || "";
    // LangGraph may re-emit the completed AIMessage after incremental tokens.
    if (prev && (content === prev || content.startsWith(prev))) {
      if (content === prev && target.status === "streaming") return;
      state.messages = [
        ...state.messages.slice(0, idx),
        {
          ...target,
          content,
          status: target.status === "done" ? "streaming" : target.status,
        },
        ...state.messages.slice(idx + 1),
      ];
      return;
    }
    const nextContent = prev + content;
    const nextStatus = target.status === "done" ? "streaming" : target.status;
    if (target.contentBlocks && target.contentBlocks.length > 0) {
      const blocks = [...target.contentBlocks];
      const lastBlock = blocks[blocks.length - 1];
      if (lastBlock.type === "text") {
        blocks[blocks.length - 1] = {
          ...lastBlock,
          content: lastBlock.content + content,
        };
      } else {
        blocks.push({ type: "text", content });
      }
      state.messages = [
        ...state.messages.slice(0, idx),
        {
          ...target,
          content: nextContent,
          contentBlocks: blocks,
          status: nextStatus,
        },
        ...state.messages.slice(idx + 1),
      ];
      return;
    }
    state.messages = [
      ...state.messages.slice(0, idx),
      { ...target, content: nextContent, status: nextStatus },
      ...state.messages.slice(idx + 1),
    ];
    return;
  }
  sealPriorStreamingAssistants(state, speaker);
  state.streamId = generateId();
  state.messages = [
    ...state.messages,
    {
      id: state.streamId,
      role: "assistant",
      content,
      status: "streaming",
      timestamp: Date.now(),
      speakerAgentId: speaker,
      ...(turnId ? { turnId } : {}),
    },
  ];
}

export /** Append a reasoning fragment as a thinking content block on the last
 *  streaming bubble (creating one if needed). Renderers that recognise
 *  contentBlocks will show it in a collapsible thinking panel. */
function appendStreamingReasoning(
  state: SessionStreamState,
  content: string,
  speakerAgentId?: string,
  turnId = "",
): void {
  if (!content) return;
  const speaker = speakerAgentId?.trim() || undefined;
  const lastIdx = findSpeakerTextToContinue(
    state.messages,
    speaker,
    sessionHostAgentId(state),
    continueTokenOpts(state),
  );
  const last = lastIdx >= 0 ? state.messages[lastIdx] : null;
  if (
    last &&
    last.role === "assistant" &&
    !last.toolData &&
    !bubbleMatchesTurn(last, turnId, state.activeTurnId)
  ) {
    sealPriorStreamingAssistants(state, speaker);
    const id = generateId();
    state.streamId = id;
    state.messages = [
      ...state.messages,
      {
        id,
        role: "assistant",
        content: "",
        contentBlocks: [{ type: "thinking", content }],
        status: "streaming",
        timestamp: Date.now(),
        speakerAgentId: speaker,
        ...(turnId ? { turnId } : {}),
      },
    ];
    return;
  }
  if (last && turnId && !last.turnId) last.turnId = turnId;
  if (last && last.role === "assistant" && !last.toolData) {
    const blocks = last.contentBlocks ? [...last.contentBlocks] : [];
    if (blocks.length > 0 && blocks[blocks.length - 1].type === "thinking") {
      const tail = blocks[blocks.length - 1];
      blocks[blocks.length - 1] = { ...tail, content: tail.content + content };
    } else {
      blocks.push({ type: "thinking", content });
    }
    const nextStatus = last.status === "done" ? "streaming" : last.status;
    state.messages = [
      ...state.messages.slice(0, lastIdx),
      {
        ...last,
        contentBlocks: blocks,
        status: nextStatus,
        speakerAgentId: speaker ?? last.speakerAgentId,
      },
      ...state.messages.slice(lastIdx + 1),
    ];
    return;
  }
  sealPriorStreamingAssistants(state, speaker);
  const id = generateId();
  state.streamId = id;
  state.messages = [
    ...state.messages,
    {
      id,
      role: "assistant",
      content: "",
      contentBlocks: [{ type: "thinking", content }],
      status: "streaming",
      timestamp: Date.now(),
      speakerAgentId: speaker,
      ...(turnId ? { turnId } : {}),
    },
  ];
}
