import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isTransportFailure } from "@/lib/api/errors";

import { createThread, getHistory, listAgents, listThreads } from "./api";
import { mockAgents, mockHistory, mockThreads } from "./mock";
import type { Agent, Thread, ThreadHistory } from "./types";

export type DataSource = "live" | "mock";

export interface Sourced<T> {
  data: T;
  source: DataSource;
}

export const chatKeys = {
  all: ["chat"] as const,
  agents: () => [...chatKeys.all, "agents"] as const,
  threads: (agentId: string) => [...chatKeys.all, "threads", agentId] as const,
  history: (agentId: string, threadId: string) =>
    [...chatKeys.all, "history", agentId, threadId] as const,
};

export function useAgents() {
  return useQuery<Sourced<Agent[]>>({
    queryKey: chatKeys.agents(),
    queryFn: async () => {
      try {
        return { data: await listAgents(), source: "live" };
      } catch (error) {
        if (!isTransportFailure(error)) throw error;
        return { data: mockAgents, source: "mock" };
      }
    },
  });
}

export function useThreads(agentId: string | undefined) {
  return useQuery<Sourced<Thread[]>>({
    queryKey: chatKeys.threads(agentId ?? ""),
    enabled: Boolean(agentId),
    queryFn: async () => {
      if (!agentId) return { data: [], source: "live" };
      try {
        return { data: await listThreads(agentId), source: "live" };
      } catch (error) {
        if (!isTransportFailure(error)) throw error;
        return { data: mockThreads, source: "mock" };
      }
    },
  });
}

export function useHistory(agentId: string | undefined, threadId: string | undefined) {
  return useQuery<Sourced<ThreadHistory>>({
    queryKey: chatKeys.history(agentId ?? "", threadId ?? ""),
    enabled: Boolean(agentId && threadId),
    // A running turn rewrites history on the server, so re-poll while it is active.
    refetchInterval: (query) =>
      query.state.data?.data.turn_active ? 2500 : false,
    queryFn: async () => {
      if (!agentId || !threadId) {
        return { data: { thread_id: "", messages: [] }, source: "live" };
      }
      try {
        return { data: await getHistory(agentId, threadId), source: "live" };
      } catch (error) {
        if (!isTransportFailure(error)) throw error;
        return { data: mockHistory, source: "mock" };
      }
    },
  });
}

export function useCreateThread(agentId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      if (!agentId) throw new Error("Pick an agent first");
      return createThread(agentId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: chatKeys.threads(agentId ?? "") });
    },
  });
}
