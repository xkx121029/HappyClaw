import { useQuery, useQueries } from "@tanstack/react-query";

import { isTransportFailure } from "@/lib/api/errors";

import {
  getActivity,
  getPendingApprovals,
  getRecentThreads,
  getUsage,
  listHomeAgents,
} from "./api";
import type { Agent } from "@/features/chat/types";

import type { HomeThread } from "./types";

export const homeKeys = {
  all: ["home"] as const,
  activity: () => [...homeKeys.all, "activity"] as const,
  usage: () => [...homeKeys.all, "usage"] as const,
  agents: () => [...homeKeys.all, "agents"] as const,
  pending: (agentId: string) => [...homeKeys.all, "pending", agentId] as const,
  threads: (agentId: string) => [...homeKeys.all, "threads", agentId] as const,
};

/**
 * Every Home query degrades to `null` when the backend is absent, so the page
 * can say "unreachable" per card instead of failing as a whole. A 4xx/5xx still
 * propagates: that is a bug, not a missing server.
 */
async function orNull<T>(run: () => Promise<T>): Promise<T | null> {
  try {
    return await run();
  } catch (error) {
    if (isTransportFailure(error)) return null;
    throw error;
  }
}

export function useActivity() {
  return useQuery({
    queryKey: homeKeys.activity(),
    queryFn: () => orNull(getActivity),
    refetchInterval: 10_000,
  });
}

export function useUsage() {
  return useQuery({
    queryKey: homeKeys.usage(),
    queryFn: () => orNull(getUsage),
    staleTime: 60_000,
  });
}

export function useAgents() {
  return useQuery({
    queryKey: homeKeys.agents(),
    queryFn: () => orNull(listHomeAgents),
  });
}

export function usePendingApprovals(agentIds: string[]) {
  return useQueries({
    queries: agentIds.map((agentId) => ({
      queryKey: homeKeys.pending(agentId),
      queryFn: () => orNull(() => getPendingApprovals(agentId)),
      refetchInterval: 15_000,
    })),
    combine: (results) => ({
      items: results.flatMap((result) => result.data ?? []),
      isPending: results.some((result) => result.isPending),
    }),
  });
}

export function useRecentThreads(agents: Agent[]) {
  const agentIds = agents.map((agent) => agent.agent_id);
  return useQueries({
    queries: agents.map((agent) => ({
      queryKey: homeKeys.threads(agent.agent_id),
      queryFn: () => orNull(() => getRecentThreads(agent)),
    })),
    combine: (results) => {
      const agents = results.map((result, index) => ({
        agentId: agentIds[index] ?? "",
        threads: result.data ?? [],
      }));
      const merged: HomeThread[] = agents
        .flatMap((entry) => entry.threads)
        .sort((left, right) => right.timestamp - left.timestamp)
        .slice(0, 6);
      return {
        threads: merged,
        isPending: results.some((result) => result.isPending),
        agentCount: agents.filter((entry) => entry.threads.length > 0).length,
      };
    },
  });
}
