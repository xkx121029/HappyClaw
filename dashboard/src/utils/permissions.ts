/** Client-side helpers mirroring backend ``user_has_permission``. */

export type PermissionHolder = {
  role: "admin" | "user" | string;
  permissions?: string[] | null;
};

/** Any-of module keys, or ``"admin"`` for role-only. */
export type PermissionKeys = readonly string[] | "admin";

export const PERM = {
  skills: ["skills"],
  subagents: ["subagents"],
  tools: ["tools"],
  agentPlugins: ["agent_plugins"],
  mbti: ["mbti"],
  memory: ["memory"],
  /** Personalization tabs other than channels, which has its own nav item. */
  personalization: [
    "skills",
    "skill_builtin",
    "skill_market",
    "subagents",
    "tools",
    "agent_plugins",
    "mbti",
    "memory",
  ],
  channels: ["channels"],
  connectors: ["connector_enabled", "connector_builtin", "connector_custom"],
  skillPackages: ["skill_packages"],
  knowledgeBases: ["knowledge_bases"],
  knowledgeSettings: ["knowledge_settings"],
  knowledgeBasesPage: ["knowledge_bases", "knowledge_settings"],
  bridge: ["bridge"],
  workbench: ["browser", "terminal"],
  browser: ["browser"],
  terminal: ["terminal"],
  desktop: ["desktop"],
  mobile: ["mobile"],
  usersPage: [
    "users",
    "user_roles",
    "user_groups",
    "sso_feishu",
    "sso_wecom",
    "sso_dingtalk",
    "sso_oidc",
    "sso_ldap",
  ],
  modelsPage: [
    "providers",
    "ollama_models",
    "onnx_models",
    "model_generation",
    "voice",
    "model_decision",
    "search",
  ],
  storage: ["storage_backends"],
  plugins: ["plugins", "plugin_market"],
  securityPage: [
    "security_hitl",
    "security_filesystem",
    "security_pii",
    "security_tool_guard",
    "security_skill_scan",
    "admin_console",
  ],
  advancedPage: ["update", "envs", "tls", "observability", "backup", "captcha"],
  experts: ["experts"],
  tasks: ["tasks"],
  tokenUsage: ["token_usage"],
} as const satisfies Record<string, readonly string[]>;

/** Sidebar item key → permission keys. Shared with path guards. */
export const PERSONALIZATION_TAB_PERMISSIONS = {
  skills: ["skills", "skill_builtin", "skill_market"],
  subagents: "subagents",
  tools: "tools",
  plugins: "agent_plugins",
  mbti: "mbti",
  memory: "memory",
  channels: "channels",
} as const;

export const CONNECTOR_TAB_PERMISSIONS = {
  enabled: "connector_enabled",
  builtin: "connector_builtin",
  custom: "connector_custom",
} as const;

export const PLUGIN_TAB_PERMISSIONS = {
  installed: "plugins",
  market: "plugin_market",
} as const;

export const NAV_PERMISSIONS = {
  experts: PERM.experts,
  tasks: PERM.tasks,
  "token-usage": PERM.tokenUsage,
  personalization: PERM.personalization,
  channels: PERM.channels,
  connectors: PERM.connectors,
  "skill-packages": PERM.skillPackages,
  "knowledge-bases": PERM.knowledgeBasesPage,
  bridge: PERM.bridge,
  workbench: PERM.workbench,
  "remote-desktop": ["desktop", "mobile"],
  "remote-phone": PERM.mobile,
  acp: "admin",
  "admin-users": PERM.usersPage,
  models: PERM.modelsPage,
  "admin-storage": PERM.storage,
  "admin-plugins": PERM.plugins,
  "admin-security": PERM.securityPage,
  "admin-advanced": PERM.advancedPage,
} as const satisfies Record<string, PermissionKeys>;

export type NavPermissionKey = keyof typeof NAV_PERMISSIONS;

export const USERS_TAB_PERMISSIONS = {
  local: "users",
  roles: "user_roles",
  groups: "user_groups",
  feishu: "sso_feishu",
  wecom: "sso_wecom",
  dingtalk: "sso_dingtalk",
  oidc: "sso_oidc",
  ldap: "sso_ldap",
} as const;

export const ADVANCED_TAB_PERMISSIONS = {
  "env-vars": "envs",
  observability: "observability",
  backup: "backup",
  https: "tls",
  updates: "update",
  captcha: "captcha",
  // Same gate as /api/settings/webauthn (require_permission("captcha")).
  webauthn: "captcha",
} as const;

export const SECURITY_TAB_PERMISSIONS = {
  hitl: "security_hitl",
  filesystem: "security_filesystem",
  pii: "security_pii",
  tool_guard: "security_tool_guard",
  skill_scan: "security_skill_scan",
  audit: "admin_console",
} as const;

/**
 * 单人本机模式：控制台不再有角色与模块权限。
 *
 * 下面这些函数保留原有签名，避免大量历史调用点同时改动；判断逻辑已收口为
 * 「本机只有一个使用者，全部功能都对自己开放」。新增界面不应再调用它们。
 */
export function userCan(
  _user: PermissionHolder | null | undefined,
  _key: string,
): boolean {
  return true;
}

/** True when the user holds any of the given keys (admin bypasses). */
export function userCanAny(
  _user: PermissionHolder | null | undefined,
  _keys: readonly string[],
): boolean {
  return true;
}

export function canAccessKeys(
  _user: PermissionHolder | null | undefined,
  _keys: PermissionKeys,
): boolean {
  return true;
}

export function navAllowed(
  _user: PermissionHolder | null | undefined,
  _navKey: NavPermissionKey,
): boolean {
  return true;
}

export function userCanKey(
  _user: PermissionHolder | null | undefined,
  _key: string | readonly string[],
): boolean {
  return true;
}

/**
 * Permissions that unlock a dashboard path (any-of).
 * 单人本机模式下没有受限路径，恒返回 ``null``。
 */
export function pathPermissionKeys(_pathname: string): PermissionKeys | null {
  return null;
}

/** True when this route config path should be wrapped in RequirePermission. */
export function routeNeedsPermission(_routePath: string): boolean {
  return false;
}

export function canAccessPath(
  _user: PermissionHolder | null | undefined,
  _pathname: string,
): boolean {
  return true;
}
