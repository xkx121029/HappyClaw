import { useCallback, useEffect, useRef, useState } from "react";

import { env } from "@/lib/env";

export type SocketStatus = "idle" | "connecting" | "open" | "closed";

/**
 * HappyClaw chat socket. The backend accepts `{type:"subscribe", thread_id}`
 * and then `{type:"user_turn", text, thread_id}`; the reply streams as harness
 * chunks and ends with `{type:"done"}`.
 *
 * This round deliberately does not decode the streaming chunk protocol: it
 * sends the turn, reports when the turn finished, and lets the caller refetch
 * history — the same data, from one source of truth. Token-level streaming is
 * its own batch in the migration plan.
 */
export function useChatSocket(
  agentId: string | undefined,
  threadId: string | undefined,
  onTurnDone: () => void,
) {
  const socketRef = useRef<WebSocket | null>(null);
  const doneRef = useRef(onTurnDone);
  const [status, setStatus] = useState<SocketStatus>(
    agentId && !env.useMockApi ? "connecting" : "idle",
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    doneRef.current = onTurnDone;
  }, [onTurnDone]);

  useEffect(() => {
    if (!agentId || env.useMockApi) return;

    const url = new URL(
      `/api/agents/${encodeURIComponent(agentId)}/chat/ws`,
      env.apiBase || window.location.origin,
    );
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";

    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      setStatus("open");
      setError(null);
    };
    socket.onclose = () => setStatus("closed");
    socket.onerror = () => setError("socket");
    socket.onmessage = (event) => {
      let frame: unknown;
      try {
        frame = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (typeof frame !== "object" || frame === null) return;
      const type = (frame as { type?: string }).type;
      if (type === "done") doneRef.current();
      if (type === "error") {
        setError(String((frame as { message?: string }).message ?? "error"));
      }
    };

    return () => {
      socket.onopen = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.onmessage = null;
      socket.close();
      socketRef.current = null;
    };
  }, [agentId]);

  // Subscribe to the selected thread; the server filters frames per thread.
  useEffect(() => {
    const socket = socketRef.current;
    if (!socket || !threadId || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "subscribe", thread_id: threadId }));
  }, [threadId, status]);

  const send = useCallback(
    (text: string) => {
      const socket = socketRef.current;
      if (!socket || socket.readyState !== WebSocket.OPEN || !threadId) return false;
      socket.send(JSON.stringify({ type: "user_turn", text, thread_id: threadId }));
      return true;
    },
    [threadId],
  );

  return { status, error, send };
}
