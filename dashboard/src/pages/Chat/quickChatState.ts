import { useSyncExternalStore } from "react";

/**
 * Which quick-chat thread is currently on screen. The chat page publishes it,
 * and the first-level nav (desktop rail / mobile tab bar) subscribes so the
 * 「快速对话」 entry can carry the selected state even though quick chats share
 * the ``/chat/:agent/:thread`` route shape.
 */
let activeQuickThreadId: string | null = null;
const listeners = new Set<() => void>();

export function setActiveQuickChatThread(id: string | null): void {
  if (id === activeQuickThreadId) return;
  activeQuickThreadId = id;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function chatThreadIdFromPath(pathname: string): string | null {
  const match = /^\/chat\/[^/]+\/([^/]+)/.exec(pathname);
  return match ? decodeURIComponent(match[1]) : null;
}

/** True when the URL search carries ``quick=1`` (the durable quick marker). */
export function isQuickChatSearch(search: string): boolean {
  return new URLSearchParams(search).get("quick") === "1";
}

/** True when ``threadId`` is the quick thread currently rendered by ChatPage. */
export function useQuickChatActive(threadId: string | null): boolean {
  const active = useSyncExternalStore(
    subscribe,
    () => activeQuickThreadId,
    () => null,
  );
  return threadId !== null && active === threadId;
}
