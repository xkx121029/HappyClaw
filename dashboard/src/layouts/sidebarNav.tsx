import type { ReactNode } from "react";
import {
  Monitor,
  MessageSquareText,
  Timer,
  SlidersHorizontal,
  Waypoints,
  Link2,
  Database,
  Cpu,
  Activity,
  Share2,
  Cloudy,
  Sparkles,
  Puzzle,
  Package,
  HardDrive,
  GraduationCap,
  Shield,
  PanelsTopLeft,
  Home,
  Zap,
  MessagesSquare,
  Smartphone,
  Info,
  Palette,
} from "lucide-react";

export const EXPANDED_WIDTH = 220;
export const COLLAPSED_WIDTH = 56;

const iconSize = 16;
const iconStroke = 1.8;

const PERSONALIZATION_NAV_TABS = [
  { key: "skills", path: "/personalization/skills" },
  { key: "subagents", path: "/personalization/subagents" },
  { key: "tools", path: "/personalization/tools" },
  { key: "agent_plugins", path: "/personalization/plugins" },
  { key: "mbti", path: "/personalization/mbti" },
  { key: "memory", path: "/personalization/memory" },
] as const;

/** 单人模式默认落在第一个可用分区；不再按权限挑选。 */
function personalizationNavPath(): string {
  return PERSONALIZATION_NAV_TABS[0].path;
}

export interface NavItem {
  key: string;
  path: string;
  icon: ReactNode;
  labelKey: string;
  badge?: string;
}

export interface NavSection {
  /** Stable group id. Omitted for the ungrouped block at the top. */
  id?: string;
  /** Built-in label key. Omitted when {@link title} is set or the block is ungrouped. */
  groupKey?: string;
  /** User-defined group title. Wins over {@link groupKey}. */
  title?: string;
  items: NavItem[];
}

/** Every nav item key the sidebar can show. Keep in sync with `SIDEBAR_NAV_KEYS` in `octop.infra.users.preferences`. */
export const SIDEBAR_NAV_KEYS = [
  "chat",
  "experts",
  "tasks",
  "token-usage",
  "mobile-sessions",
  "mobile-control",
  "mobile-info",
  "personalization",
  "channels",
  "connectors",
  "skill-packages",
  "knowledge-bases",
  "bridge",
  "workbench",
  "remote-desktop",
  "acp",
  "models",
  "admin-storage",
  "admin-plugins",
  "admin-security",
  "admin-advanced",
] as const;

export const BUILTIN_NAV_GROUP_IDS = [
  "mobile",
  "settings",
  "control",
  "admin",
] as const;

const BUILTIN_NAV_GROUP_LABEL_KEYS: Record<
  (typeof BUILTIN_NAV_GROUP_IDS)[number],
  string
> = {
  mobile: "nav.mobileSection",
  settings: "nav.settings",
  control: "nav.control",
  admin: "nav.admin",
};

export function isBuiltinNavGroupId(id: string): boolean {
  return (BUILTIN_NAV_GROUP_IDS as readonly string[]).includes(id);
}

export function builtinNavGroupLabelKey(id: string): string | null {
  if (!isBuiltinNavGroupId(id)) return null;
  return BUILTIN_NAV_GROUP_LABEL_KEYS[
    id as (typeof BUILTIN_NAV_GROUP_IDS)[number]
  ];
}

export function navSectionLabel(
  section: NavSection,
  translate: (key: string) => string,
): string {
  if (section.title) return section.title;
  if (section.groupKey) return translate(section.groupKey);
  return "";
}

/**
 * Catalog of nav item keys that live under the settings group.
 * Permission-independent — used for pane/route helpers; visibility still
 * comes from {@link buildNavSections}.
 */
export const SIDEBAR_GROUPED_NAV_KEYS = [
  "mobile-sessions",
  "mobile-control",
  "mobile-info",
  "personalization",
  "channels",
  "connectors",
  "skill-packages",
  "knowledge-bases",
  "bridge",
  "workbench",
  "remote-desktop",
  "acp",
  "token-usage",
  "models",
  "admin-storage",
  "admin-plugins",
  "admin-security",
  "admin-advanced",
  "agent-config",
] as const;

const GROUPED_NAV_KEY_SET = new Set<string>(SIDEBAR_GROUPED_NAV_KEYS);

export function isGroupedNavKey(key: string): boolean {
  return GROUPED_NAV_KEY_SET.has(key);
}

/**
 * Two levels, not five groups.
 *
 * The sidebar used to expose 23 destinations across five groups, so half of the
 * first level was configuration and administration — for a single-owner
 * workspace that buries the four daily destinations (home / chat / experts /
 * tasks). Everything configurable now lives under one collapsible 设置 group;
 * the routes are unchanged, so bookmarks and deep links still work.
 */
export function buildNavSections(): NavSection[] {
  const topItems: NavItem[] = [
    {
      // Pinned above the customizable catalog: Home is the landing page and is
      // intentionally excluded from the nav customizer (see Sidebar.tsx).
      key: "home",
      path: "/home",
      icon: <Home size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.home",
    },
    {
      key: "chat",
      path: "/chat",
      icon: <MessageSquareText size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.chat",
    },
    {
      // First-level destination next to 对话: a reusable, workspace-free
      // conversation with the default expert. ``?quick=1`` is consumed by the
      // chat page, and the selected state comes from the open thread being a
      // quick one (see quickChatState.ts). Pinned like Home: the nav customizer
      // never owns it, and a saved layout cannot hide it.
      key: "quick-chat",
      path: "/chat?quick=1",
      icon: <Zap size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.quickChat",
    },
    {
      key: "experts",
      path: "/experts",
      icon: <GraduationCap size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.experts",
    },
    {
      key: "tasks",
      path: "/tasks",
      icon: <Timer size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.tasks",
    },
  ];
  const sections: NavSection[] = [{ items: topItems }];

  const settingsItems: NavItem[] = [
    {
      key: "personalization",
      path: personalizationNavPath(),
      icon: <Sparkles size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.personalization",
    },
    {
      key: "channels",
      path: "/personalization/channels",
      icon: <Waypoints size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.channels",
    },
    {
      key: "connectors",
      path: "/connectors",
      icon: <Link2 size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.connectors",
    },
    {
      key: "skill-packages",
      path: "/skill-packages",
      icon: <Package size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.skillPackages",
    },
    {
      key: "knowledge-bases",
      path: "/knowledge-bases",
      icon: <Database size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.knowledgeBases",
    },
    {
      key: "bridge",
      path: "/bridge",
      icon: <Cloudy size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.bridge",
    },
    {
      key: "workbench",
      path: "/workbench",
      icon: <PanelsTopLeft size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.workbench",
    },
    {
      // 本机远控：桌面端与手机端共用一个入口。
      key: "remote-desktop",
      path: "/remote-desktop",
      icon: <Monitor size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.remoteDesktop",
    },
    {
      key: "acp",
      path: "/acp",
      icon: <Share2 size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.acp",
    },
    {
      key: "token-usage",
      path: "/token-usage",
      icon: <Activity size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.tokenUsage",
    },
    {
      key: "mobile-sessions",
      path: "/mobile/sessions",
      icon: <MessagesSquare size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.mobileSessions",
    },
    {
      key: "mobile-control",
      path: "/mobile/control",
      icon: <Smartphone size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.mobileControl",
    },
    {
      key: "mobile-info",
      path: "/mobile/info",
      icon: <Info size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.mobileInfo",
    },
    {
      key: "models",
      path: "/admin/models",
      icon: <Cpu size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.models",
    },
    {
      key: "admin-storage",
      path: "/admin/backend",
      icon: <HardDrive size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.adminStorage",
    },
    {
      key: "admin-plugins",
      path: "/admin/plugins",
      icon: <Puzzle size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.adminPlugins",
    },
    {
      key: "admin-security",
      path: "/admin/security",
      icon: <Shield size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.security",
    },
    {
      key: "appearance",
      path: "/admin/appearance",
      icon: <Palette size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.appearance",
    },
    {
      key: "admin-advanced",
      path: "/admin/advanced",
      icon: <SlidersHorizontal size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.adminAdvanced",
    },
  ];
  sections.push({
    id: "settings",
    groupKey: "nav.settings",
    items: settingsItems,
  });
  return sections;
}
