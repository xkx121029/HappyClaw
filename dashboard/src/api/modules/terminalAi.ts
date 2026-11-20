import { request } from "../request";

export interface TerminalContext {
  os: string;
  distro: string;
  shell: string;
  hostname: string;
  username: string;
  workspace_dir: string;
  agent_id: string;
  agent_name: string;
}

/** Bundled terminal expert. Distinct from the cloud ops expert. */
export const OPS_ENGINEER_EXPERT_ID = "ops-engineer";

export interface CreatedOpsEngineer {
  id: number;
  agent_id: string;
  name: string;
  description: string;
  state: string;
  expert_id: string;
}

export const terminalAiApi = {
  getContext: (agentId: string, threadId?: string | null) =>
    request<TerminalContext>(
      `/agents/${agentId}/terminal/context${
        threadId ? `?thread_id=${encodeURIComponent(threadId)}` : ""
      }`,
    ),

  createOpsEngineer: () =>
    request<CreatedOpsEngineer>(
      `/agents/from-expert/${OPS_ENGINEER_EXPERT_ID}`,
      {
        method: "POST",
        body: JSON.stringify({}),
      },
    ),
};
