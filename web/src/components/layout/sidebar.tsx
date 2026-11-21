import {
  ChevronLeft,
  Languages,
  MessageSquare,
  Moon,
  Palette,
  PanelLeft,
  Settings,
  Sun,
} from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { env } from "@/lib/env";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/stores/ui";

interface NavItem {
  to: string;
  labelKey: "nav.chat" | "nav.settings" | "nav.design";
  icon: ReactNode;
}

const mainItems: NavItem[] = [
  { to: "/chat", labelKey: "nav.chat", icon: <MessageSquare /> },
];

const manageItems: NavItem[] = [
  { to: "/settings", labelKey: "nav.settings", icon: <Settings /> },
  { to: "/design", labelKey: "nav.design", icon: <Palette /> },
];

export function Sidebar({
  pathname,
  onNavigate,
  className,
}: {
  pathname: string;
  onNavigate?: () => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);

  const renderItem = (item: NavItem) => {
    const active = pathname === item.to || pathname.startsWith(`${item.to}/`);
    const link = (
      <a
        key={item.to}
        href={item.to}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className={cn(
          "group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-base transition-colors",
          "[&_svg]:size-4 [&_svg]:shrink-0",
          active
            ? "bg-selected text-fg [&_svg]:text-accent-fg"
            : "text-fg-muted hover:bg-hover hover:text-fg",
          collapsed && "justify-center px-0",
        )}
      >
        {item.icon}
        {collapsed ? null : <span className="truncate">{t(item.labelKey)}</span>}
      </a>
    );
    return collapsed ? (
      <Tooltip key={item.to} content={t(item.labelKey)} side="right">
        {link}
      </Tooltip>
    ) : (
      link
    );
  };

  return (
    <aside
      className={cn(
        "flex h-full flex-col border-r border-line bg-surface",
        "transition-[width] duration-(--hc-duration-base) ease-out",
        collapsed ? "w-sidebar-collapsed" : "w-sidebar",
        className,
      )}
    >
      <div
        className={cn(
          "flex h-topbar shrink-0 items-center gap-2 border-b border-line-subtle px-3",
          collapsed && "justify-center px-0",
        )}
      >
        <img
          src="/brand/happyclaw-icon.svg"
          alt=""
          className="size-6 shrink-0 rounded-sm"
        />
        {collapsed ? null : (
          <span className="text-md font-semibold tracking-tight">
            {t("app.name")}
          </span>
        )}
      </div>

      <nav
        aria-label={t("nav.groupMain")}
        className="flex flex-1 flex-col gap-5 overflow-y-auto px-2 py-3"
      >
        <div className="grid gap-0.5">{mainItems.map(renderItem)}</div>
        <div className="grid gap-0.5">
          {collapsed ? (
            <div className="mx-auto mb-1 h-px w-6 bg-line-subtle" />
          ) : (
            <p className="px-2.5 pb-1 text-2xs font-medium uppercase tracking-wide text-fg-subtle">
              {t("nav.groupManage")}
            </p>
          )}
          {manageItems.map(renderItem)}
        </div>
      </nav>

      <div className="border-t border-line-subtle p-2">
        <Button
          variant="ghost"
          size={collapsed ? "icon-sm" : "sm"}
          onClick={toggleSidebar}
          aria-label={
            collapsed ? t("shell.expandSidebar") : t("shell.collapseSidebar")
          }
          className={cn(
            "w-full justify-start text-fg-subtle",
            collapsed && "justify-center",
          )}
        >
          {collapsed ? <PanelLeft /> : <ChevronLeft />}
          {collapsed ? null : (
            <span className="text-xs">{t("shell.collapseSidebar")}</span>
          )}
        </Button>
        {collapsed ? null : (
          <p className="px-2.5 pt-1 text-2xs text-fg-subtle">
            {t("shell.version", { version: env.appVersion })}
          </p>
        )}
      </div>
    </aside>
  );
}

export function ThemeLanguageControls() {
  const { t } = useTranslation();
  const theme = useUiStore((state) => state.theme);
  const toggleTheme = useUiStore((state) => state.toggleTheme);
  const locale = useUiStore((state) => state.locale);
  const setLocale = useUiStore((state) => state.setLocale);

  return (
    <div className="flex items-center gap-1">
      <Tooltip content={t("shell.toggleTheme")}>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={toggleTheme}
          aria-label={t("shell.toggleTheme")}
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
      </Tooltip>
      <Tooltip content={t("shell.switchLanguage")}>
        <Button
          variant="ghost"
          size="sm"
          aria-label={t("shell.switchLanguage")}
          onClick={() => setLocale(locale === "zh" ? "en" : "zh")}
          className="gap-1.5 px-2 text-xs text-fg-muted"
        >
          <Languages />
          {locale === "zh" ? "中" : "EN"}
        </Button>
      </Tooltip>
    </div>
  );
}
