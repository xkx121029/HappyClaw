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
  "appearance",
  "admin-advanced",
] as const;

export const BUILTIN_NAV_GROUP_IDS = ["settings", "control", "admin"] as const;

const BUILTIN_NAV_GROUP_LABEL_KEYS: Record<
  (typeof BUILTIN_NAV_GROUP_IDS)[number],
  string
> = {
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
 * Catalog of nav item keys that live under settings / control / admin groups.
 * Permission-independent — used for pane/route helpers; visibility still
 * comes from {@link buildNavSections}.
 */
export const SIDEBAR_GROUPED_NAV_KEYS = [
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
  "appearance",
  "admin-advanced",
  "agent-config",
] as const;

const GROUPED_NAV_KEY_SET = new Set<string>(SIDEBAR_GROUPED_NAV_KEYS);

export function isGroupedNavKey(key: string): boolean {
  return GROUPED_NAV_KEY_SET.has(key);
}

export function buildNavSections(_opts?: {
  mobileEnabled?: boolean;
}): NavSection[] {
  const topItems: NavItem[] = [
    {
      key: "chat",
      path: "/chat",
      icon: <MessageSquareText size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.chat",
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
    {
      key: "token-usage",
      path: "/token-usage",
      icon: <Activity size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.tokenUsage",
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
  ];
  sections.push({
    id: "settings",
    groupKey: "nav.settings",
    items: settingsItems,
  });

  const controlItems: NavItem[] = [
    {
      key: "workbench",
      path: "/workbench",
      icon: <PanelsTopLeft size={iconSize} strokeWidth={iconStroke} />,
      labelKey: "nav.workbench",
    },
  ];
  // 本机远控：桌面端与手机端共用一个入口。
  controlItems.push({
    key: "remote-desktop",
    path: "/remote-desktop",
    icon: <Monitor size={iconSize} strokeWidth={iconStroke} />,
    labelKey: "nav.remoteDesktop",
  });
  controlItems.push({
    key: "acp",
    path: "/acp",
    icon: <Share2 size={iconSize} strokeWidth={iconStroke} />,
    labelKey: "nav.acp",
  });
  sections.push({
    id: "control",
    groupKey: "nav.control",
    items: controlItems,
  });

  const adminItems: NavItem[] = [
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
  sections.push({ id: "admin", groupKey: "nav.admin", items: adminItems });
  return sections;
}
