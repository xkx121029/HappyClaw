/**
 * Module-level chat store that survives React component unmount/remount cycles.
 *
 * Key idea: WebSocket streams and accumulated messages live *outside* React.
 * Components subscribe to updates and get the latest snapshot on mount.
 * When the user navigates away and comes back, the messages (including
 * any in-flight streaming content) are still available.
 *
 * The implementation lives in the sibling `chatStore*.ts` modules; this file
 * is the facade that keeps the original import surface intact.
 */

export type {
  ChatAttachment,
  ChatMessage,
  HitlActionRequest,
  HitlRequestData,
  SessionSnapshot,
  SessionStreamState,
  ToolCallData,
  UserComposerContext,
} from "./sseHelpers";

export type { ToolEventKind, ToolEvent, StreamEventKind, StreamEvent, SlashActionEvent, SessionEventKind, SessionEvent, SteerRestoreEvent, SharedTurnBusyEvent } from "./chatStoreTypes";
export { onToolEvent, emitToolEvent, onStreamEvent, onSlashAction, onSessionEvent, emitSessionEvent, onSteerRestore, onSharedTurnBusy } from "./chatStoreEvents";
export { subscribe, getSnapshot, beginHistoryRead, isHistoryReadCurrent } from "./chatStorePublish";
export { setPendingPlanPath, setMessages, setHistoryPage, restoreInflightTail, invalidateHistory, isHistoryStale, prependHistoryMessages, setHistoryLoadingMore, appendUserMessage, truncateAndReplaceUserMessage, appendPushMessage, clearMessages } from "./chatStoreHistory";
export { getFocusedChatSession, setPendingPrefillText, consumePendingPrefillText, setPendingPrefillAttachments, consumePendingPrefillAttachments } from "./chatStoreFocus";
export { hasLiveSocket } from "./chatStoreSocket";
export { cancelStream, removeSession, detachSessionKey, renameSessionKey, resolveSessionKey, debugDump } from "./chatStoreSessionLifecycle";
export { setSessionTeamRoom } from "./chatStoreTurns";
export { patchToolResultData } from "./chatStoreToolCalls";
export { ingestHarnessChunk } from "./chatStoreStream";
export { sharedTurnBlocksSender, sendSteerWhileBusy, withdrawCommittedSteer, getActiveTurnId } from "./chatStoreSteer";
export { setFocusedChatSession, attachThread } from "./chatStoreAttach";
export { sendTurn, resumeHitl } from "./chatStoreSend";
