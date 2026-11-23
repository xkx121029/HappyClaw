/**
 * Policy-form helpers shared by the Admin → Users and Admin → Roles screens:
 * mapping a role's resource limits into form values and back into the API
 * payload.
 */

import type { UserRole } from "../../../api/modules/userRoles";
import type { PolicyFormValues } from "./usersListTypes";

export function policyFieldsFromRole(
  role: UserRole,
  workspaceRootAllowed: boolean,
): PolicyFormValues {
  return {
    limit_workspace_root:
      workspaceRootAllowed && Boolean(role.workspace_root_dir),
    workspace_root_dir: role.workspace_root_dir ?? undefined,
    limit_token_quota: role.token_quota != null,
    token_quota: role.token_quota ?? undefined,
    limit_max_agents: role.max_agents != null,
    max_agents: role.max_agents ?? undefined,
  };
}

export function policyPayload(
  values: PolicyFormValues,
  options: { workspaceRootAllowed: boolean },
): {
  workspace_root_dir: string | null;
  token_quota: number | null;
  max_agents: number | null;
} {
  return {
    workspace_root_dir:
      options.workspaceRootAllowed && values.limit_workspace_root
        ? values.workspace_root_dir?.trim() || null
        : null,
    token_quota: values.limit_token_quota ? values.token_quota ?? null : null,
    max_agents: values.limit_max_agents ? values.max_agents ?? null : null,
  };
}

export function rolePoliciesFromForm(
  values: PolicyFormValues,
  options: { workspaceRootAllowed: boolean },
): { name: string; value: string }[] {
  const flat = policyPayload(values, options);
  const policies: { name: string; value: string }[] = [];
  if (flat.workspace_root_dir) {
    policies.push({
      name: "workspace_root_dir",
      value: flat.workspace_root_dir,
    });
  }
  if (flat.token_quota != null) {
    policies.push({ name: "token_quota", value: String(flat.token_quota) });
  }
  if (flat.max_agents != null) {
    policies.push({ name: "max_agents", value: String(flat.max_agents) });
  }
  return policies;
}
