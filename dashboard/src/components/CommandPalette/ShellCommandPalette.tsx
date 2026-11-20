import { useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Activity,
  Bot,
  Cloudy,
  Cpu,
  Database,
  GraduationCap,
  HardDrive,
  Home,
  Info,
  Keyboard,
  Link2,
  MessageSquareText,
  MessagesSquare,
  Monitor,
  Package,
  PanelsTopLeft,
  Puzzle,
  Share2,
  Shield,
  SlidersHorizontal,
  Smartphone,
  Sparkles,
  Timer,
  Waypoints,
  Zap,
} from "lucide-react";

import PaletteSurface, {
  type PaletteGroup,
  type PaletteItem,
} from "../CommandPalette/PaletteSurface";
import { buildNavSections } from "../../layouts/sidebarNav";

/** Palette-side icons; `sidebarNav` builds React nodes, not components. */
const NAV_ICONS: Record<string, PaletteItem["icon"]> = {
  home: Home,
  chat: MessageSquareText,
  "quick-chat": Zap,
  experts: GraduationCap,
  tasks: Timer,
  personalization: Sparkles,
  channels: Waypoints,
  connectors: Link2,
  "skill-packages": Package,
  "knowledge-bases": Database,
  bridge: Cloudy,
  workbench: PanelsTopLeft,
  "remote-desktop": Monitor,
  acp: Share2,
  "token-usage": Activity,
  "mobile-sessions": MessagesSquare,
  "mobile-control": Smartphone,
  "mobile-info": Info,
  models: Cpu,
  "admin-storage": HardDrive,
  "admin-plugins": Puzzle,
  "admin-security": Shield,
  "admin-advanced": SlidersHorizontal,
  "agent-config": Bot,
};

interface ShellCommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onOpenShortcuts: () => void;
}

/**
 * Shell-level command palette (Ctrl/Cmd + K from any page).
 *
 * The chat page keeps its own richer palette (sessions + models); this one makes
 * every destination reachable without hunting through the sidebar. Both render
 * through `PaletteSurface`, so the keyboard model is identical.
 */
export default function ShellCommandPalette({
  open,
  onClose,
  onOpenShortcuts,
}: ShellCommandPaletteProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const groups = useMemo<PaletteGroup[]>(() => {
    const go = (path: string) => () => navigate(path);
    const navGroups: PaletteGroup[] = buildNavSections().map(
      (section, index) => ({
        kind: section.id ?? `flat-${index}`,
        label: section.title
          ? section.title
          : section.groupKey
          ? t(section.groupKey)
          : t("nav.common", "常用"),
        items: section.items.map((item) => ({
          id: `nav:${item.key}`,
          label: t(item.labelKey),
          meta: item.path,
          icon: NAV_ICONS[item.key],
          run: go(item.path),
        })),
      }),
    );

    return [
      ...navGroups,
      {
        kind: "help",
        label: t("palette.groupHelp", "帮助"),
        items: [
          {
            id: "shortcuts",
            label: t("palette.shortcuts", "查看全部键盘快捷键"),
            icon: Keyboard,
            run: onOpenShortcuts,
          },
        ],
      },
    ];
  }, [navigate, onOpenShortcuts, t]);

  const emptyActions = useMemo<PaletteItem[]>(
    () => [
      {
        id: "go-home",
        label: t("palette.goHome", "回到主页"),
        icon: Home,
        run: () => navigate("/home"),
      },
      {
        id: "shortcuts",
        label: t("palette.shortcuts", "查看全部键盘快捷键"),
        icon: Keyboard,
        run: onOpenShortcuts,
      },
    ],
    [navigate, onOpenShortcuts, t],
  );

  return (
    <PaletteSurface
      open={open}
      onClose={onClose}
      label={t("palette.placeholder", "搜索页面、设置项或操作…")}
      placeholder={t("palette.placeholder", "搜索页面、设置项或操作…")}
      groups={groups}
      emptyText={t("palette.noResults", "没有匹配的页面，换个关键词试试。")}
      emptyActions={emptyActions}
      footerHint={t("palette.footer", "↑↓ 选择 · ↵ 打开 · Esc 关闭")}
      footerNote={t("palette.localOnly", "仅本机")}
    />
  );
}

/**
 * Ctrl/Cmd+K anywhere in the shell.
 *
 * The chat page binds the same key for its richer palette and calls
 * `preventDefault`, so this handler yields whenever a page already took it.
 */
export function useShellPaletteShortcut(
  enabled: boolean,
  onOpen: () => void,
): void {
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (!mod || event.defaultPrevented) return;
      if (event.key.toLowerCase() !== "k" || event.shiftKey || event.altKey) {
        return;
      }
      event.preventDefault();
      onOpen();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled, onOpen]);
}
