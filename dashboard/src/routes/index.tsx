import { lazy } from "react";
import { Navigate, useLocation } from "react-router-dom";

// Lazy-loaded pages — Common
const HomePage = lazy(() => import("../pages/Home"));
const ExpertsPage = lazy(() => import("../pages/Experts"));
const CronJobsPage = lazy(() => import("../pages/Control/CronJobs"));
const ConnectorsPage = lazy(() => import("../pages/Agent/Connectors"));
const SkillPackagesPage = lazy(() => import("../pages/SkillPackages"));
const KnowledgeBasesPage = lazy(() => import("../pages/KnowledgeBases"));
const BridgePage = lazy(() => import("../pages/Settings/Bridge"));
const PersonalizationPage = lazy(
  () => import("../pages/Agent/Personalization"),
);
const ACPPage = lazy(() => import("../pages/Agent/ACP"));
const TokenUsagePage = lazy(() => import("../pages/Control/TokenUsage"));

// Lazy-loaded pages — Control
const RemoteDesktopPage = lazy(() => import("../pages/Control/RemoteDesktop"));
const SoloPage = lazy(() => import("../pages/Solo"));
const BaoPage = lazy(() => import("../components/Bao/BaoPage"));

// Lazy-loaded pages — 手机板块
const MobileSessionsPage = lazy(
  () => import("../pages/Mobile/MobileSessions"),
);
const MobileControlPage = lazy(() => import("../pages/Mobile/MobileControl"));
const MobileInfoPage = lazy(() => import("../pages/Mobile/MobileInfo"));

// Lazy-loaded pages — Settings
const ModelsPage = lazy(() => import("../pages/Settings/Models"));

// Lazy-loaded pages — Admin
const AdminSecurityPage = lazy(() => import("../pages/Settings/Security"));
const AdvancedSettingsPage = lazy(
  () => import("../pages/Settings/AdvancedSettings"),
);
const AdminStoragePage = lazy(() => import("../pages/Admin/Storage"));
const AdminPluginsPage = lazy(() => import("../pages/Admin/Plugins"));
const AppearanceSettingsPage = lazy(() => import("../pages/Settings/Appearance"));
const AgentConfigPage = lazy(() => import("../pages/Agent/Config"));

// Misc
const PwaDebugPage = lazy(() => import("../pages/PwaDebug"));
const MotionPreviewPage = lazy(() => import("../pages/MotionPreview"));
const NotFoundPage = lazy(() => import("../components/NotFoundPage"));

function RedirectPreserveSearch({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={`${to}${location.search}${location.hash}`} replace />;
}

export interface RouteConfig {
  path: string;
  element: React.ReactNode;
  /** When true, the route uses a wrapper component instead of a plain element */
  useWrapper?: boolean;
}

export const pathToKey: Record<string, string> = {
  "/home": "home",
  "/chat": "chat",
  // Common
  "/experts": "experts",
  "/tasks": "tasks",
  "/connectors": "connectors",
  "/skill-packages": "skill-packages",
  "/knowledge-bases": "knowledge-bases",
  "/bridge": "bridge",
  "/personalization": "personalization",
  "/personalization/skills": "personalization",
  "/personalization/tools": "personalization",
  "/personalization/plugins": "personalization",
  "/personalization/subagents": "personalization",
  "/personalization/channels": "channels",
  "/personalization/mbti": "personalization",
  "/personalization/memory": "personalization",
  "/skills": "personalization",
  "/token-usage": "token-usage",
  "/agent-config": "agent-config",
  // Control
  "/acp": "acp",
  "/channels": "channels",
  "/workbench": "workbench",
  "/workbench/terminal": "workbench",
  "/workbench/browser": "workbench",
  "/workbench/cloud": "workbench",
  "/terminal": "workbench",
  "/remote-browser": "workbench",
  "/remote-desktop": "remote-desktop",
  "/remote-desktop/desktop": "remote-desktop",
  "/remote-desktop/link": "remote-desktop",
  // 手机板块
  "/mobile/sessions": "mobile-sessions",
  "/mobile/control": "mobile-control",
  "/mobile/info": "mobile-info",
  // Legacy aliases (redirected to /remote-desktop/link)
  "/remote-phone": "remote-desktop",
  "/subagents": "personalization",
  "/mbti": "personalization",
  "/memory": "personalization",
  // Admin
  "/admin/models": "models",
  // Admin
  "/admin/backend": "admin-storage",
  "/admin/plugins": "admin-plugins",
  "/admin/advanced": "admin-advanced",
  "/admin/appearance": "appearance",
  "/admin/security": "admin-security",
  "/motion-preview": "motion-preview",
};

/**
 * Pages that should fill the entire content area without padding/scroll wrapper.
 */
export const FULLSCREEN_PATHS = new Set([
  "/workbench",
  "/workbench/terminal",
  "/workbench/browser",
  "/workbench/cloud",
  "/chat",
  "/solo",
  "/bao",
  "/remote-desktop",
  "/remote-desktop/desktop",
  "/remote-desktop/link",
  "/remote-desktop/pair",
]);

/**
 * Pages that provide their own compact mobile header.
 */
export const SELF_HEADER_PATHS = new Set<string>(["/bao", "/chat"]);

/** Mobile-only fullscreen pages (custom header + no content padding). */
export const MOBILE_FULLSCREEN_PATHS = new Set<string>([]);

export function isWorkbenchPath(pathname: string): boolean {
  return pathname === "/workbench" || pathname.startsWith("/workbench/");
}

export function isRemoteDesktopPath(pathname: string): boolean {
  return (
    pathname === "/remote-desktop" || pathname.startsWith("/remote-desktop/")
  );
}

export function isPersonalizationPath(pathname: string): boolean {
  return (
    pathname === "/personalization" || pathname.startsWith("/personalization/")
  );
}

export function resolveSelectedKey(pathname: string): string {
  if (pathToKey[pathname]) return pathToKey[pathname];
  if (pathname.startsWith("/chat/")) return "chat";
  if (pathname.startsWith("/workbench/")) return "workbench";
  if (pathname.startsWith("/remote-desktop/")) return "remote-desktop";
  if (pathname.startsWith("/personalization/")) return "personalization";
  return "";
}

export const routeConfigs: RouteConfig[] = [
  // Home — real-time activity dashboard and default landing page.
  { path: "/home", element: <HomePage /> },

  // Chat (handled via ChatWithKey wrapper in MainLayout)
  { path: "/chat", element: null, useWrapper: true },
  { path: "/chat/:agentId", element: null, useWrapper: true },
  { path: "/chat/:agentId/:threadId", element: null, useWrapper: true },

  // 手机板块（手机会话 / 手机控制 / 手机信息）
  { path: "/mobile/sessions", element: <MobileSessionsPage /> },
  { path: "/mobile/control", element: <MobileControlPage /> },
  { path: "/mobile/info", element: <MobileInfoPage /> },

  // SOLO workspace（会话 / 对话 / 编辑器 + 终端 / 文件树）
  { path: "/solo", element: <SoloPage /> },

  // 宝：Router 页面（全局 / 项目作用域通过 ?project= 区分）
  { path: "/bao", element: <BaoPage /> },

  // Common
  { path: "/experts", element: <ExpertsPage /> },
  { path: "/tasks", element: <CronJobsPage /> },
  { path: "/connectors", element: <ConnectorsPage /> },
  { path: "/skill-packages", element: <SkillPackagesPage /> },
  { path: "/knowledge-bases", element: <KnowledgeBasesPage /> },
  { path: "/bridge", element: <BridgePage /> },
  {
    path: "/personalization/acp",
    element: <RedirectPreserveSearch to="/acp" />,
  },
  { path: "/personalization/*", element: <PersonalizationPage /> },
  {
    path: "/skills",
    element: <RedirectPreserveSearch to="/personalization/skills" />,
  },
  { path: "/token-usage", element: <TokenUsagePage /> },

  // Control (RequirePermission via pathPermissionKeys in MainLayout)
  { path: "/acp", element: <ACPPage /> },
  {
    path: "/channels",
    element: <RedirectPreserveSearch to="/personalization/channels" />,
  },
  // Workbench (terminal + browser) is keep-alive mounted in MainLayout.
  { path: "/workbench", element: null },
  { path: "/workbench/terminal", element: null },
  { path: "/workbench/browser", element: null },
  { path: "/workbench/cloud", element: null },
  {
    path: "/terminal",
    element: <RedirectPreserveSearch to="/workbench/terminal" />,
  },
  {
    path: "/remote-browser",
    element: <RedirectPreserveSearch to="/workbench/browser" />,
  },
  { path: "/remote-desktop", element: <RemoteDesktopPage /> },
  { path: "/remote-desktop/desktop", element: <RemoteDesktopPage /> },
  {
    path: "/remote-desktop/phone",
    element: <RedirectPreserveSearch to="/remote-desktop/link" />,
  },
  { path: "/remote-desktop/link", element: <RemoteDesktopPage /> },
  { path: "/remote-desktop/pair", element: <RemoteDesktopPage /> },
  {
    path: "/remote-desktop/phone/screen",
    element: <RedirectPreserveSearch to="/remote-desktop/link" />,
  },
  {
    path: "/remote-desktop/phone/shell",
    element: <RedirectPreserveSearch to="/remote-desktop/link" />,
  },
  {
    path: "/remote-phone",
    element: <RedirectPreserveSearch to="/remote-desktop/link" />,
  },
  {
    path: "/remote-android",
    element: <RedirectPreserveSearch to="/remote-desktop/link" />,
  },
  {
    path: "/subagents",
    element: <RedirectPreserveSearch to="/personalization/subagents" />,
  },
  {
    path: "/mbti",
    element: <RedirectPreserveSearch to="/personalization/mbti" />,
  },
  {
    path: "/memory",
    element: <RedirectPreserveSearch to="/personalization/memory" />,
  },
  { path: "/workspace", element: <Navigate to="/experts" replace /> },

  // Settings
  { path: "/admin/models", element: <ModelsPage /> },

  // 单人模式：成员 / 邀请 / SSO 管理入口已移除，旧链接回首页。
  { path: "/admin/users", element: <Navigate to="/chat" replace /> },
  { path: "/admin/sso", element: <Navigate to="/chat" replace /> },
  {
    path: "/admin/shared-models",
    element: <Navigate to="/admin/models" replace />,
  },
  { path: "/models", element: <Navigate to="/admin/models" replace /> },
  { path: "/admin/backend", element: <AdminStoragePage /> },
  {
    path: "/admin/audit",
    element: <Navigate to="/admin/security?tab=audit" replace />,
  },
  { path: "/admin/agents", element: <Navigate to="/chat" replace /> },
  { path: "/admin/plugins", element: <AdminPluginsPage /> },
  { path: "/admin/advanced", element: <AdvancedSettingsPage /> },
  { path: "/admin/appearance", element: <AppearanceSettingsPage /> },
  { path: "/admin/security", element: <AdminSecurityPage /> },
  {
    path: "/admin/voice",
    element: <Navigate to="/admin/models?tab=voice" replace />,
  },
  {
    path: "/admin/updates",
    element: <Navigate to="/admin/advanced?tab=updates" replace />,
  },

  // Legacy redirects — keeps old bookmarks working
  { path: "/admin/storage", element: <Navigate to="/admin/backend" replace /> },
  { path: "/orca/cron", element: <Navigate to="/tasks" replace /> },
  { path: "/orca/channels", element: <Navigate to="/channels" replace /> },
  {
    path: "/orca/admin/users",
    element: <Navigate to="/chat" replace />,
  },
  {
    path: "/orca/admin/audit",
    element: <Navigate to="/admin/security?tab=audit" replace />,
  },
  { path: "/octop/cron", element: <Navigate to="/tasks" replace /> },
  { path: "/octop/channels", element: <Navigate to="/channels" replace /> },
  {
    path: "/octop/admin/users",
    element: <Navigate to="/chat" replace />,
  },
  {
    path: "/octop/admin/audit",
    element: <Navigate to="/admin/security?tab=audit" replace />,
  },
  {
    path: "/advanced-settings",
    element: <Navigate to="/admin/advanced" replace />,
  },
  { path: "/environments", element: <Navigate to="/admin/advanced" replace /> },
  { path: "/agent-config", element: <AgentConfigPage /> },
  {
    path: "/updates",
    element: <Navigate to="/admin/advanced?tab=updates" replace />,
  },
  {
    path: "/plugins",
    element: <Navigate to="/admin/plugins" replace />,
  },
  { path: "/sessions", element: <Navigate to="/chat" replace /> },
  { path: "/cron-jobs", element: <Navigate to="/tasks" replace /> },

  // Misc
  { path: "/pwa-debug", element: <PwaDebugPage /> },
  // 动效样例：不进入主导航，直接从地址访问，供设计走查使用。
  { path: "/motion-preview", element: <MotionPreviewPage /> },
  { path: "/", element: <Navigate to="/home" replace /> },
  { path: "*", element: <NotFoundPage /> },
];
