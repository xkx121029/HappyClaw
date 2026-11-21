import { useEffect, useRef } from "react";
import type { ChatMessage } from "./useChat";

const PRESENT_FILE_TOOL = "present_file";

/** Read the workspace-relative path from a ``present_file`` tool result. */
export function presentedFilePath(output: unknown): string {
  if (typeof output !== "string" || !output.trim()) return "";
  try {
    const parsed = JSON.parse(output) as {
      status?: unknown;
      path?: unknown;
    };
    if (parsed?.status !== "ok") return "";
    return typeof parsed.path === "string" ? parsed.path.trim() : "";
  } catch {
    return "";
  }
}

/**
 * Let the agent pull out the chat dock: a completed ``present_file`` call
 * opens its workspace file in a dock tab, in the current thread scope.
 * Results already present while history loads are marked as seen, so opening
 * an old conversation never yanks the panel open by itself.
 */
export function useChatPresentFile(
  threadId: string | null,
  messages: ChatMessage[],
  historyHydrated: boolean,
  openFileAt: (path: string, agentId?: string | null) => void,
  agentId?: string | null,
) {
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    seenRef.current = new Set();
  }, [threadId]);

  useEffect(() => {
    for (const m of messages) {
      const tool = m.toolData;
      if (!tool || tool.name !== PRESENT_FILE_TOOL) continue;
      const path = presentedFilePath(tool.output);
      if (!path) continue;
      const key = tool.callId || m.id;
      if (seenRef.current.has(key)) continue;
      seenRef.current.add(key);
      if (!historyHydrated) continue;
      openFileAt(path, m.speakerAgentId?.trim() || agentId || null);
    }
  }, [messages, historyHydrated, openFileAt, agentId]);
}
