import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { isTransportFailure } from "@/lib/api/errors";
import type { Agent } from "@/features/chat/types";

/** Runtime knobs of one agent. `null` means "use the server default". */
export interface AgentRuntimeConfig {
  name: string;
  description: string;
  default_model: string;
  system_prompt: string;
  max_iters: number | null;
  max_input_length: number | null;
  temperature: number | null;
  top_p: number | null;
  max_tokens: number | null;
}

export interface AgentRow extends Omit<Agent, "description" | "default_model"> {
  description?: string | null;
  default_model?: string | null;
  system_prompt?: string | null;
  max_iters?: number | null;
  max_input_length?: number | null;
  temperature?: number | null;
  top_p?: number | null;
  max_tokens?: number | null;
}

const numOrNull = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

export function toConfig(row: AgentRow): AgentRuntimeConfig {
  return {
    name: row.name ?? "",
    description: row.description ?? "",
    default_model: row.default_model ?? "",
    system_prompt: row.system_prompt ?? "",
    max_iters: numOrNull(row.max_iters),
    max_input_length: numOrNull(row.max_input_length),
    temperature: numOrNull(row.temperature),
    top_p: numOrNull(row.top_p),
    max_tokens: numOrNull(row.max_tokens),
  };
}

export async function listAgentRows(): Promise<AgentRow[]> {
  const { data } = await api.GET("/api/agents", { params: { query: { scope: "mine" } } });
  const rows: unknown[] = Array.isArray(data) ? data : [];
  return rows.filter(
    (row): row is AgentRow =>
      typeof row === "object" &&
      row !== null &&
      typeof (row as AgentRow).agent_id === "string" &&
      typeof (row as AgentRow).name === "string",
  );
}

export async function saveAgentConfig(
  agentId: string,
  config: AgentRuntimeConfig,
): Promise<void> {
  await api.PATCH("/api/agents/{agent_id}", {
    params: { path: { agent_id: agentId } },
    body: {
      name: config.name || undefined,
      description: config.description,
      default_model: config.default_model || null,
      system_prompt: config.system_prompt,
      max_iters: config.max_iters,
      max_input_length: config.max_input_length,
      temperature: config.temperature,
      top_p: config.top_p,
      max_tokens: config.max_tokens,
    },
  });
}

export function useAgentRows() {
  return useQuery({
    queryKey: ["agent-config", "rows"],
    queryFn: async () => {
      try {
        return await listAgentRows();
      } catch (error) {
        if (isTransportFailure(error)) return null;
        throw error;
      }
    },
  });
}

export function useSaveAgentConfig(agentId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (config: AgentRuntimeConfig) => {
      if (!agentId) throw new Error("Pick an agent first");
      await saveAgentConfig(agentId, config);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-config", "rows"] });
    },
  });
}

/** True when any field differs from what the server returned. */
export function isDirty(
  original: AgentRuntimeConfig,
  draft: AgentRuntimeConfig,
): boolean {
  return (Object.keys(original) as (keyof AgentRuntimeConfig)[]).some(
    (key) => original[key] !== draft[key],
  );
}
