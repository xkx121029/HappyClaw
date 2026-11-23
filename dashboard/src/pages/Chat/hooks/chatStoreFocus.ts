/**
 * Which conversation the UI is showing, plus the composer prefill handoff for the next Chat mount.
 */

import { type ChatAttachment } from "./sseHelpers";

export // ── Focused chat session (reconnect thrash only for the visible tab) ──────

let focusedChatSessionId: string | null = null;

export function getFocusedChatSession(): string | null {
  return focusedChatSessionId;
}

export function isSessionFocused(sessionId: string): boolean {
  // Unset focus (unit tests / before first paint) → treat as focused.
  if (focusedChatSessionId == null) return true;
  return focusedChatSessionId === sessionId;
}

export // ── Pending prefill text ──────────────────────────────────────────────────
// Set by external pages (e.g. cron-jobs suggestions) before navigating to
// /chat so the Chat input can be pre-populated reliably without relying on
// React Router location.state, which can be unreliable across mounts.
let _pendingPrefillText = "";

/** Enqueue a text to be pre-filled into the chat input on the next Chat mount. */
export function setPendingPrefillText(text: string): void {
  _pendingPrefillText = text;
}

/** Consume the pending prefill text (clears it after reading). */
export function consumePendingPrefillText(): string {
  const val = _pendingPrefillText;
  _pendingPrefillText = "";
  return val;
}

export let _pendingPrefillAttachments: ChatAttachment[] = [];

/** Enqueue attachments to restore in the composer on the next Chat mount / thread switch. */
export function setPendingPrefillAttachments(
  attachments: ChatAttachment[],
): void {
  _pendingPrefillAttachments = attachments.map((attachment) => ({
    ...attachment,
  }));
}

/** Consume pending prefill attachments (clears after reading). */
export function consumePendingPrefillAttachments(): ChatAttachment[] {
  const val = _pendingPrefillAttachments;
  _pendingPrefillAttachments = [];
  return val.map((attachment) => ({ ...attachment }));
}

/** Point the store at a session id without running any socket side effects. */
export function assignFocusedChatSession(sessionId: string | null): void {
  focusedChatSessionId = sessionId;
}
