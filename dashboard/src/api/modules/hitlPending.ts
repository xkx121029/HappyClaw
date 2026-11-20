import { request, requestStream } from "../request";
import type { AskQuestion } from "../types/hitl";

/** One paused HITL turn, projected for the Home inbox. */
export interface PendingHitlItem {
  pendingId: string;
  agentId: string;
  threadId: string;
  sessionTitle: string | null;
  createdAtMs: number;
  /** ``question`` is ``ask_user_question``; ``approval`` needs the chat page. */
  kind: "question" | "approval";
  questions: AskQuestion[];
  actionRequests: Array<{ name: string; description?: string | null }>;
}

interface PendingHitlResponse {
  ok: boolean;
  items: PendingHitlItem[];
}

interface AnswerBody {
  agentId: string;
  threadId: string;
  pendingId: string;
  message: string;
}

/** Pull the first error message out of an SSE body, if the resume failed. */
function sseError(text: string): string | null {
  for (const line of text.split("\n")) {
    if (!line.startsWith("data:")) continue;
    const raw = line.slice(5).trim();
    if (!raw) continue;
    try {
      const frame = JSON.parse(raw) as { type?: string; message?: string };
      if (frame.type === "error" && frame.message) return frame.message;
    } catch {
      // Keep scanning: a partial/unknown frame must not mask a later error.
    }
  }
  return null;
}

/**
 * Read-only HITL listing plus the existing resume endpoint.
 *
 * Answering posts to ``/chat/hitl/resume`` exactly like the chat page; this
 * module never resolves a pause locally.
 */
export const hitlPendingApi = {
  list: (agentId: string) =>
    request<PendingHitlResponse>(
      `/agents/${encodeURIComponent(agentId)}/chat/hitl/pending`,
    ),

  answer: async (body: AnswerBody): Promise<void> => {
    const { body: stream } = await requestStream(
      `/agents/${encodeURIComponent(body.agentId)}/chat/hitl/resume`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: body.threadId,
          pending_id: body.pendingId,
          decisions: [{ type: "respond", message: body.message }],
        }),
      },
    );
    // Drain the SSE so the server finishes the resume before the card settles.
    const text = await new Response(stream).text();
    const error = sseError(text);
    if (error) throw new Error(error);
  },
};
