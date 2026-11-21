/** Map sidebar paths to their lazy route chunks for hover prefetch. */
const ROUTE_PREFETCHERS: Record<string, () => Promise<unknown>> = {
  "/home": () => import("../pages/Home"),
  "/chat": () => import("../pages/Chat"),
  "/chat?quick=1": () => import("../pages/Chat"),
  "/experts": () => import("../pages/Experts"),
  "/tasks": () => import("../pages/Control/CronJobs"),
  "/connectors": () => import("../pages/Agent/Connectors"),
  "/skill-packages": () => import("../pages/SkillPackages"),
  "/knowledge-bases": () => import("../pages/KnowledgeBases"),
  "/skills": () => import("../pages/Agent/Personalization"),
  "/token-usage": () => import("../pages/Control/TokenUsage"),
  "/channels": () => import("../pages/Agent/Personalization"),
  "/workbench": () => import("../pages/Control/Workbench"),
  "/workbench/browser": () => import("../pages/Control/Workbench"),
  "/workbench/terminal": () => import("../pages/Control/Workbench"),
  "/workbench/cloud": () => import("../pages/Control/Workbench"),
  "/remote-desktop": () => import("../pages/Control/RemoteDesktop"),
  "/remote-desktop/desktop": () => import("../pages/Control/RemoteDesktop"),
  "/remote-desktop/phone": () => import("../pages/Control/RemoteDesktop"),
  "/remote-desktop/link": () => import("../pages/Control/RemoteDesktop"),
  "/remote-desktop/pair": () => import("../pages/Control/RemoteDesktop"),
  "/remote-phone": () => import("../pages/Control/RemoteDesktop"),
  "/remote-android": () => import("../pages/Control/RemoteDesktop"),
  "/mobile/sessions": () => import("../pages/Mobile/MobileSessions"),
  "/mobile/control": () => import("../pages/Mobile/MobileControl"),
  "/mobile/info": () => import("../pages/Mobile/MobileInfo"),
  "/acp": () => import("../pages/Agent/ACP"),
  "/personalization": () => import("../pages/Agent/Personalization"),
  "/personalization/skills": () => import("../pages/Agent/Personalization"),
  "/personalization/tools": () => import("../pages/Agent/Personalization"),
  "/personalization/acp": () => import("../pages/Agent/ACP"),
  "/personalization/subagents": () => import("../pages/Agent/Personalization"),
  "/personalization/channels": () => import("../pages/Agent/Personalization"),
  "/personalization/mbti": () => import("../pages/Agent/Personalization"),
  "/personalization/memory": () => import("../pages/Agent/Personalization"),
  "/subagents": () => import("../pages/Agent/Personalization"),
  "/mbti": () => import("../pages/Agent/Personalization"),
  "/memory": () => import("../pages/Agent/Personalization"),
  "/admin/models": () => import("../pages/Settings/Models"),
  "/admin/backend": () => import("../pages/Admin/Storage"),
  "/admin/plugins": () => import("../pages/Admin/Plugins"),
  "/admin/security": () => import("../pages/Settings/Security"),
  "/admin/advanced": () => import("../pages/Settings/AdvancedSettings"),
  "/agent-config": () => import("../pages/Agent/Config"),
  // First-class sidebar entries rendered outside buildNavSections (custom
  // buttons in Sidebar.tsx) — keep them prefetchable on hover, like the rest.
  "/solo": () => import("../pages/Solo"),
  "/bao": () => import("../components/Bao/BaoPage"),
  "/bridge": () => import("../pages/Settings/Bridge"),
};

export const ROUTE_PREFETCH_PATHS: readonly string[] = Object.freeze(
  Object.keys(ROUTE_PREFETCHERS),
);

export function prefetchRoute(path: string): void {
  const load = ROUTE_PREFETCHERS[path];
  if (load) void load();
}
