import type {
  ResolvedRoute,
  RouteSpec,
  TransitionCatalog,
  TransitionModule,
} from "./types";

/** 模块顺序 = 侧栏自上而下的顺序，跨模块转场的方向由它决定。 */
export const MODULE_ORDER: Record<TransitionModule, number> = {
  home: 0,
  chat: 1,
  solo: 2,
  bao: 3,
  agent: 4,
  control: 5,
  settings: 6,
  admin: 7,
  debug: 8,
  misc: 9,
};

/**
 * 全站路由声明表。
 *
 * 新增页面时只在下面加一条：声明 module / depth / kind 即可，
 * 需要共享元素接力时补 shared，需要复用页面实例时补 stage。
 */
export const DEFAULT_ROUTE_SPECS: RouteSpec[] = [
  // ── Home ────────────────────────────────────────────────────────────────
  {
    path: "/home",
    module: "home",
    depth: 0,
    kind: "hub",
    shared: ["thread-title"],
  },

  // ── Chat（会话切换复用同一页面实例）────────────────────────────────────
  { path: "/chat", module: "chat", depth: 0, kind: "list", stage: "chat" },
  {
    path: "/chat/:agentId",
    module: "chat",
    depth: 0,
    kind: "list",
    stage: "chat",
  },
  {
    path: "/chat/:agentId/:threadId",
    module: "chat",
    depth: 1,
    kind: "conversation",
    stage: "chat",
    shared: ["thread-title"],
  },

  // ── 独立工作台 ──────────────────────────────────────────────────────────
  { path: "/solo", module: "solo", depth: 0, kind: "workspace" },
  { path: "/bao", module: "bao", depth: 0, kind: "workspace" },

  // ── Agent / 个人中心 ────────────────────────────────────────────────────
  { path: "/experts", module: "agent", depth: 0, kind: "list" },
  { path: "/connectors", module: "agent", depth: 0, kind: "list" },
  { path: "/skill-packages", module: "agent", depth: 0, kind: "list" },
  {
    path: "/knowledge-bases",
    module: "agent",
    depth: 0,
    kind: "list",
    shared: ["kb-title"],
  },
  { path: "/bridge", module: "agent", depth: 0, kind: "detail" },
  {
    path: "/personalization/*",
    module: "agent",
    depth: 0,
    kind: "tab",
    stage: "personalization",
  },
  // 个人中心页签的别名路由（重定向后仍在同一页实例内）
  {
    path: "/personalization/acp",
    module: "agent",
    depth: 0,
    kind: "tab",
    stage: "personalization",
  },
  {
    path: "/skills",
    module: "agent",
    depth: 0,
    kind: "tab",
    stage: "personalization",
  },
  {
    path: "/subagents",
    module: "agent",
    depth: 0,
    kind: "tab",
    stage: "personalization",
  },
  {
    path: "/mbti",
    module: "agent",
    depth: 0,
    kind: "tab",
    stage: "personalization",
  },
  {
    path: "/memory",
    module: "agent",
    depth: 0,
    kind: "tab",
    stage: "personalization",
  },
  {
    path: "/channels",
    module: "agent",
    depth: 0,
    kind: "tab",
    stage: "personalization",
  },
  { path: "/agent-config", module: "agent", depth: 1, kind: "detail" },
  {
    path: "/workspace",
    module: "agent",
    depth: 0,
    kind: "list",
    stage: "/experts",
  },

  // ── Control ─────────────────────────────────────────────────────────────
  { path: "/tasks", module: "control", depth: 0, kind: "list" },
  {
    path: "/cron-jobs",
    module: "control",
    depth: 0,
    kind: "list",
    stage: "/tasks",
  },
  {
    path: "/orca/cron",
    module: "control",
    depth: 0,
    kind: "list",
    stage: "/tasks",
  },
  {
    path: "/orca/channels",
    module: "agent",
    depth: 0,
    kind: "tab",
    stage: "personalization",
  },
  {
    path: "/orca/admin/users",
    module: "chat",
    depth: 0,
    kind: "list",
    stage: "chat",
  },
  {
    path: "/orca/admin/audit",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-security",
  },
  {
    path: "/octop/cron",
    module: "control",
    depth: 0,
    kind: "list",
    stage: "/tasks",
  },
  // 手机板块（手机会话 / 手机控制 / 手机信息）共用页面实例，切换不播转场
  {
    path: "/mobile/sessions",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "mobile",
  },
  {
    path: "/mobile/control",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "mobile",
  },
  {
    path: "/mobile/info",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "mobile",
  },
  { path: "/token-usage", module: "control", depth: 0, kind: "detail" },
  { path: "/acp", module: "control", depth: 0, kind: "detail" },
  // Workbench（终端 / 浏览器 / 云）共用页面实例
  {
    path: "/workbench",
    module: "control",
    depth: 0,
    kind: "workspace",
    stage: "workbench",
  },
  {
    path: "/workbench/terminal",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "workbench",
  },
  {
    path: "/workbench/browser",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "workbench",
  },
  {
    path: "/workbench/cloud",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "workbench",
  },
  {
    path: "/terminal",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "workbench",
  },
  {
    path: "/remote-browser",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "workbench",
  },
  // 远程桌面（桌面 / 链接）共用页面实例
  {
    path: "/remote-desktop",
    module: "control",
    depth: 0,
    kind: "workspace",
    stage: "remote-desktop",
  },
  {
    path: "/remote-desktop/desktop",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "remote-desktop",
  },
  {
    path: "/remote-desktop/link",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "remote-desktop",
  },
  {
    path: "/remote-desktop/pair",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "remote-desktop",
  },
  {
    path: "/remote-desktop/phone",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "remote-desktop",
  },
  {
    path: "/remote-desktop/phone/screen",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "remote-desktop",
  },
  {
    path: "/remote-desktop/phone/shell",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "remote-desktop",
  },
  {
    path: "/remote-phone",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "remote-desktop",
  },
  {
    path: "/remote-android",
    module: "control",
    depth: 0,
    kind: "tab",
    stage: "remote-desktop",
  },

  // ── Settings / Admin ────────────────────────────────────────────────────
  {
    path: "/admin/models",
    module: "settings",
    depth: 0,
    kind: "list",
    stage: "models",
  },
  {
    path: "/models",
    module: "settings",
    depth: 0,
    kind: "list",
    stage: "models",
  },
  {
    path: "/admin/backend",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-storage",
  },
  {
    path: "/admin/storage",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-storage",
  },
  {
    path: "/admin/plugins",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-plugins",
  },
  {
    path: "/plugins",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-plugins",
  },
  {
    path: "/admin/appearance",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-advanced",
  },
  {
    path: "/admin/advanced",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-advanced",
  },
  {
    path: "/advanced-settings",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-advanced",
  },
  {
    path: "/environments",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-advanced",
  },
  {
    path: "/updates",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-advanced",
  },
  {
    path: "/admin/updates",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-advanced",
  },
  {
    path: "/admin/security",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-security",
  },
  {
    path: "/admin/audit",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-security",
  },
  {
    path: "/octop/admin/audit",
    module: "settings",
    depth: 1,
    kind: "detail",
    stage: "admin-security",
  },
  // 已下线入口：重定向到聊天页，按聊天页承接
  {
    path: "/admin/users",
    module: "chat",
    depth: 0,
    kind: "list",
    stage: "chat",
  },
  { path: "/admin/sso", module: "chat", depth: 0, kind: "list", stage: "chat" },
  {
    path: "/admin/agents",
    module: "chat",
    depth: 0,
    kind: "list",
    stage: "chat",
  },
  {
    path: "/octop/admin/users",
    module: "chat",
    depth: 0,
    kind: "list",
    stage: "chat",
  },
  { path: "/sessions", module: "chat", depth: 0, kind: "list", stage: "chat" },
  {
    path: "/admin/shared-models",
    module: "settings",
    depth: 0,
    kind: "list",
    stage: "models",
  },
  {
    path: "/admin/voice",
    module: "settings",
    depth: 0,
    kind: "list",
    stage: "models",
  },
  {
    path: "/octop/channels",
    module: "agent",
    depth: 0,
    kind: "tab",
    stage: "personalization",
  },

  // ── Misc ────────────────────────────────────────────────────────────────
  { path: "/pwa-debug", module: "debug", depth: 0, kind: "list" },
  { path: "/motion-preview", module: "debug", depth: 0, kind: "detail" },
  { path: "/", module: "home", depth: 0, kind: "hub", stage: "/home" },
  { path: "*", module: "misc", depth: 0, kind: "fallback", stage: "not-found" },
];

function patternToRegExp(pattern: string): RegExp {
  const source = pattern
    .split("/")
    .map((segment) =>
      segment.startsWith(":")
        ? "[^/]+"
        : segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
    )
    .join("/");
  return new RegExp(`^${source}$`);
}

/**
 * 用一组声明生成路由转场目录。
 * 库本体不写死任何路由，页面侧只维护声明表。
 */
export function createTransitionCatalog(
  specs: RouteSpec[] = DEFAULT_ROUTE_SPECS,
): TransitionCatalog {
  const exact = new Map<string, RouteSpec>();
  const patterns: Array<{ re: RegExp; spec: RouteSpec }> = [];
  const prefixes: Array<{ base: string; spec: RouteSpec }> = [];
  let fallback: RouteSpec | undefined;

  for (const spec of specs) {
    if (spec.path === "*") {
      fallback = spec;
      continue;
    }
    if (spec.path.endsWith("/*")) {
      prefixes.push({ base: spec.path.slice(0, -2), spec });
      continue;
    }
    if (spec.path.includes(":")) {
      patterns.push({ re: patternToRegExp(spec.path), spec });
      continue;
    }
    if (exact.has(spec.path)) {
      throw new Error(`[page-transitions] 重复声明的路由：${spec.path}`);
    }
    exact.set(spec.path, spec);
  }

  const resolve = (pathname: string): ResolvedRoute => {
    const clean = pathname.split("?")[0].split("#")[0] || "/";
    const hit = exact.get(clean);
    if (hit) {
      return {
        spec: hit,
        path: clean,
        stage: hit.stage ?? clean,
        matched: "exact",
      };
    }
    for (const { re, spec } of patterns) {
      if (re.test(clean)) {
        return {
          spec,
          path: clean,
          stage: spec.stage ?? clean,
          matched: "pattern",
        };
      }
    }
    // 前缀声明按最长前缀优先，避免 /workbench/* 抢走更具体的声明。
    const prefix = prefixes
      .filter(({ base }) => clean === base || clean.startsWith(`${base}/`))
      .sort((a, b) => b.base.length - a.base.length)[0];
    if (prefix) {
      return {
        spec: prefix.spec,
        path: clean,
        stage: prefix.spec.stage ?? clean,
        matched: "prefix",
      };
    }
    const spec = fallback ?? {
      path: "*",
      module: "misc",
      depth: 0,
      kind: "fallback",
      stage: "not-found",
    };
    return {
      spec,
      path: clean,
      stage: spec.stage ?? "not-found",
      matched: "fallback",
    };
  };

  return { specs, resolve };
}

export const routeCatalog = createTransitionCatalog();

export function resolveRoute(pathname: string): ResolvedRoute {
  return routeCatalog.resolve(pathname);
}
