/** Route helpers for the standalone mobile shell. */

export interface MobileTabItem {
  key: "home" | "quick" | "chat" | "bao" | "experts" | "more";
  /** Tab root path. */
  path: string;
  /** Fallback Chinese label; components translate it. */
  label: string;
  /** Label key used by i18n (falls back to ``label``). */
  labelKey: string;
}

export const TAB_ITEMS: MobileTabItem[] = [
  { key: "home", path: "/m/home", label: "首页", labelKey: "mobile.tabs.home" },
  {
    key: "quick",
    path: "/m/quick",
    label: "快速对话",
    labelKey: "mobile.tabs.quick",
  },
  { key: "chat", path: "/m/chat", label: "对话", labelKey: "mobile.tabs.chat" },
  { key: "bao", path: "/m/bao", label: "宝", labelKey: "mobile.tabs.bao" },
  {
    key: "experts",
    path: "/m/experts",
    label: "专家",
    labelKey: "mobile.tabs.experts",
  },
  { key: "more", path: "/m/more", label: "我的", labelKey: "mobile.tabs.more" },
];

const LEGACY_EXACT: Record<string, string> = {
  "/": "/m/home",
  "/home": "/m/home",
  "/experts": "/m/experts",
  "/bao": "/m/bao",
  "/tasks": "/m/tasks",
  "/cronjobs": "/m/tasks",
  "/connectors": "/m/connectors",
  "/knowledge-bases": "/m/knowledge-bases",
  "/token-usage": "/m/token-usage",
  "/personalization": "/m/personalization",
  "/skills": "/m/more",
  "/skill-packages": "/m/more",
  "/agent-config": "/m/more",
  "/bridge": "/m/more",
  "/acp": "/m/more",
};

const LEGACY_PREFIX: Array<[string, string]> = [
  ["/chat", "/m/chat"],
  ["/admin", "/m/admin"],
  ["/personalization/", "/m/personalization/"],
];

function trimTrailingSlash(pathname: string): string {
  if (pathname.length > 1 && pathname.endsWith("/")) {
    return pathname.replace(/\/+$/, "") || "/";
  }
  return pathname;
}

/**
 * Translate a desktop (or legacy) pathname into the mobile route tree.
 * Paths that already live under ``/m`` are returned unchanged.
 */
export function mobilePathFor(pathname: string): string {
  const clean = trimTrailingSlash(pathname || "/");
  if (clean === "/m" || clean.startsWith("/m/")) return clean;
  const exact = LEGACY_EXACT[clean];
  if (exact) return exact;
  for (const [prefix, target] of LEGACY_PREFIX) {
    if (clean === prefix || clean.startsWith(`${prefix}/`)) {
      return target + clean.slice(prefix.length);
    }
  }
  return "/m/home";
}

/** True when the current path is a bottom-tab root (tab bar visible). */
export function isMobileTabRoot(pathname: string): boolean {
  const clean = trimTrailingSlash(pathname || "/");
  return TAB_ITEMS.some((item) => item.path === clean);
}

/** Active tab key for a pathname (chat sub-routes still belong to chat). */
export function activeTabKey(pathname: string): MobileTabItem["key"] | null {
  const clean = trimTrailingSlash(pathname || "/");
  if (clean === "/m/quick") return "quick";
  if (clean === "/m/chat" || clean.startsWith("/m/chat/")) return "chat";
  const hit = TAB_ITEMS.find((item) => item.path === clean);
  return hit ? hit.key : null;
}

/** Build a chat URL, optionally with agent/thread. */
export function chatPath(agentId?: string | null, threadId?: string | null) {
  if (agentId && threadId) return `/m/chat/${agentId}/${threadId}`;
  if (agentId) return `/m/chat/${agentId}`;
  return "/m/chat";
}
