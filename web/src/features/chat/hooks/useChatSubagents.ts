import { useEffect, useState } from "react";
import {
  listAgentSubagents,
  type AgentSubagentSummary,
} from "../lib/subagentsApi";

/** Installed workspace subagents for the running chat agent (empty if not ready). */
export function useChatSubagents(
  agentId: string | null,
): AgentSubagentSummary[] {
  const [subagents, setSubagents] = useState<AgentSubagentSummary[]>([]);

  useEffect(() => {
    if (!agentId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- external-store sync, ported as-is (see CHAT-LOGIC.md)
      setSubagents([]);
      return;
    }
    let cancelled = false;
    void listAgentSubagents(agentId)
      .then((rows) => {
        if (!cancelled) setSubagents(rows);
      })
      .catch(() => {
        if (!cancelled) setSubagents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  return subagents;
}
