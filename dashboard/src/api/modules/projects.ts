import { request } from "../request";

export interface Project {
  project_id: string;
  name: string;
  root_dir: string | null;
  is_default: boolean;
  origin: string;
  created_at: number;
  updated_at: number;
}

export interface ProjectThread {
  thread_id: string;
  agent_id: string;
  title: string;
  channel_type: string;
  last_active: number;
  created_at: number;
  pinned: boolean;
  project_id: string;
  workspace_kind: string | null;
  workspace_dir: string | null;
}

export interface CreateProjectBody {
  name: string;
  root_dir?: string | null;
}

export const projectsApi = {
  list: () => request<Project[]>("/projects"),

  create: (body: CreateProjectBody) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  rename: (projectId: string, name: string) =>
    request<Project>(`/projects/${encodeURIComponent(projectId)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  remove: (projectId: string) =>
    request<{ ok: boolean; threads_unbound: number }>(
      `/projects/${encodeURIComponent(projectId)}`,
      { method: "DELETE" },
    ),

  threads: (projectId: string, limit = 100) =>
    request<ProjectThread[]>(
      `/projects/${encodeURIComponent(projectId)}/threads?limit=${limit}`,
    ),
};
