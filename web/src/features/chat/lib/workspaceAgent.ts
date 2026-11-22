import { request } from "./http";

export interface CreateWorkspaceAgentResult {
  agentId: string;
  reused: boolean;
}

/**
 * Create an expert copy whose home *is* the chosen folder.
 *
 * ``workspace_dir`` is the only knob that changes the harness working
 * directory (the shell cwd and the file-tool root both follow it). It only
 * takes effect when the backend is rooted at the host root, so we send the
 * host-root sentinel and let the server re-scope it to the workspace on
 * Windows. The chosen folder therefore becomes the agent home.
 */
export async function createWorkspaceAgent(options: {
  templateId: string;
  name: string;
  workspaceDir: string;
}): Promise<CreateWorkspaceAgentResult> {
  const res = await request<{ agent_id?: string; reused?: boolean }>(
    `/agents/from-expert/${encodeURIComponent(options.templateId)}`,
    {
      method: "POST",
      body: JSON.stringify({
        name: options.name,
        workspace_dir: options.workspaceDir,
        backend: { type: "local_shell", root_dir: "/", virtual_mode: true },
      }),
    },
  );
  if (!res.agent_id) {
    throw new Error("workspace agent create returned no agent_id");
  }
  return { agentId: res.agent_id, reused: Boolean(res.reused) };
}
