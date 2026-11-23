/**
 * Shared types and constants for the Admin → Users screen.
 *
 * Extracted verbatim from `UsersListPanel.tsx` so the panels, drawers and
 * hooks built on top of it can share one description of the user row, the
 * permission catalog and the policy form.
 */

export interface UserRow {
  id: number;
  username: string;
  /** Role-template public id: admin | user | custom ULID. */
  role: string;
  display_name: string | null;
  email?: string | null;
  has_password?: boolean;
  sso_linked?: boolean;
  directory?: boolean;
  disabled: boolean;
  login_failed_count?: number;
  login_locked?: boolean;
  login_locked_until?: number;
  login_retry_after_seconds?: number;
  created_at?: number;
  permissions?: string[];
  role_name?: string | null;
  avatar_url?: string | null;
  avatar_icon?: string | null;
  workspace_root_dir?: string | null;
  token_quota?: number | null;
  max_agents?: number | null;
  /** Present when the users list includes MFA status from the backend. */
  mfa_active?: boolean;
}

export interface PermissionCatalogItem {
  key: string;
  category: string;
  label: string;
  page?: string;
  page_label?: string;
}

export function permFullLabel(item: PermissionCatalogItem): string {
  if (item.page_label) return `${item.page_label} / ${item.label}`;
  return item.label;
}

export interface PolicyFormValues {
  limit_workspace_root?: boolean;
  workspace_root_dir?: string;
  limit_token_quota?: boolean;
  token_quota?: number | null;
  limit_max_agents?: boolean;
  max_agents?: number | null;
}

export const DEFAULT_EXPERT_TEMPLATE_ID = "general-assistant";

export interface ExpertTemplateOption {
  id: string;
  label: string;
  description?: string;
  icon_url?: string | null;
  icon_name?: string | null;
}

export interface CreateValues extends PolicyFormValues {
  username: string;
  display_name?: string;
  email?: string;
  directory?: boolean;
  password?: string;
  confirm?: string;
  role: string;
  permissions?: string[];
  role_name?: string | null;
  create_default_expert?: boolean;
  expert_template_id?: string;
}

export interface EditValues extends PolicyFormValues {
  display_name?: string;
  email?: string;
  role: string;
  permissions?: string[];
  role_name?: string | null;
}

export interface ResetValues {
  password: string;
  confirm: string;
}

export type BatchAction =
  | "enable"
  | "disable"
  | "delete"
  | "set_token_quota"
  | "set_max_agents";

export interface BatchResponse {
  action: BatchAction;
  results: {
    user_id: number;
    ok: boolean;
    error?: string | null;
    code?: string | null;
  }[];
  succeeded: number;
  failed: number;
}

export interface BatchTokenFormValues {
  limit_token_quota?: boolean;
  token_quota?: number | null;
}

export interface BatchMaxAgentsFormValues {
  limit_max_agents?: boolean;
  max_agents?: number | null;
}

export const FIELD_ICON_PROPS = {
  size: 16 as const,
  style: { color: "var(--fn-text-tertiary)" },
};
