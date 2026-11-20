import { useEffect, useMemo, useState } from "react";
import { request } from "@/api/request";
import type { OctopAgent } from "@/context/AgentContext";

export interface AgentWorkspaceInfo {
  agentId: string;
  name: string;
  templateName: string | null;
  /** Resolved execution directory; null when the agent has no explicit one. */
  workspaceDir: string | null;
}

interface AgentDetail {
  agent_id?: string;
  name?: string;
  template_name?: string | null;
  config?: { workspace_dir?: string | null } | null;
}

interface FilesystemDefaults {
  default_workspace_dir?: string | null;
}

function normalizeDir(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

/** 归一化工作区路径，供按 ``workspace_dir`` 归组时比较（大小写/斜杠/尾斜杠）。 */
export function normalizeWorkspaceDir(path: string): string {
  return normalizeDir(path);
}

export function workspaceBasename(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  const parts = trimmed.split(/[\\/]/);
  return parts[parts.length - 1] || trimmed;
}

/** True when *path* is the agent-home default (``…/agents/<agentId>``). */
export function isDefaultWorkspacePath(
  path: string | null,
  agentsRoot: string | null,
): boolean {
  if (!path || !agentsRoot) return false;
  return normalizeDir(path).startsWith(`${normalizeDir(agentsRoot)}/`);
}

/**
 * Resolve each agent's execution directory.
 *
 * The workspace is a property of the expert/agent (its home), so the chat page
 * reads it from ``GET /agents/{id}`` instead of inventing a per-conversation
 * folder the backend cannot honour. Fetched lazily and cached per agent.
 */
export function useAgentWorkspaces(
  agents: OctopAgent[],
  enabled: boolean,
): {
  byAgent: Record<string, AgentWorkspaceInfo>;
  agentsRoot: string | null;
  /** True once the default-root lookup finished (or a root was already known). */
  rootReady: boolean;
  loading: boolean;
} {
  const [byAgent, setByAgent] = useState<Record<string, AgentWorkspaceInfo>>({});
  const [agentsRoot, setAgentsRoot] = useState<string | null>(null);
  const [rootLoaded, setRootLoaded] = useState(false);
  const [loading, setLoading] = useState(false);

  const idsKey = useMemo(
    () => agents.map((agent) => agent.agent_id).sort().join(","),
    [agents],
  );

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const missing = agents.filter((agent) => !byAgent[agent.agent_id]);
    if (missing.length === 0) return;

    setLoading(true);
    void Promise.all(
      missing.map(async (agent) => {
        try {
          const detail = await request<AgentDetail>(
            `/agents/${encodeURIComponent(agent.agent_id)}`,
          );
          return {
            agentId: agent.agent_id,
            name: detail.name || agent.name,
            templateName:
              detail.template_name ?? agent.template_name ?? null,
            workspaceDir: detail.config?.workspace_dir?.trim() || null,
          } satisfies AgentWorkspaceInfo;
        } catch {
          return {
            agentId: agent.agent_id,
            name: agent.name,
            templateName: agent.template_name ?? null,
            workspaceDir: null,
          } satisfies AgentWorkspaceInfo;
        }
      }),
    ).then((rows) => {
      if (cancelled) return;
      setByAgent((prev) => {
        const next = { ...prev };
        for (const row of rows) next[row.agentId] = row;
        return next;
      });
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [agents, byAgent, enabled, idsKey]);

  useEffect(() => {
    if (!enabled || agentsRoot) return;
    let cancelled = false;
    void request<FilesystemDefaults>("/filesystem/defaults")
      .then((defaults) => {
        if (cancelled) return;
        const root = defaults.default_workspace_dir?.trim() || null;
        if (root) setAgentsRoot(root.replace(/\\/g, "/"));
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setRootLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [agentsRoot, enabled]);

  return {
    byAgent,
    agentsRoot,
    rootReady: agentsRoot !== null || rootLoaded,
    loading,
  };
}
