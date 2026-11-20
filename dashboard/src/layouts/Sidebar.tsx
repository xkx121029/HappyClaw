import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import AvatarDropdown from "../components/AvatarDropdown";
import { useBao } from "../components/Bao/BaoContext";
import AppVersionBadge from "../components/AppVersionBadge";
import { Mascot, mascotStatusInk } from "../components/Mascot";
import CurrentVersionBadge from "../components/CurrentVersionBadge";
import {
  ArrowLeftRight,
  ChevronDown,
  Search,
  SquareTerminal,
  X,
} from "lucide-react";
import cx from "classnames";
import { useTheme } from "../context/ThemeContext";
import { useLayoutMode } from "../context/LayoutModeContext";
import { useDesktopChromeStyle } from "../hooks/useDesktopChrome";
import { useUpdateStatus } from "../hooks/useUpdateStatus";
import { prefetchRoute } from "../routes/prefetch";
import { EXPAND_CHAT_RAIL_EVENT } from "../pages/Chat/chatRailEvents";
import { SHELL_PALETTE_EVENT } from "../components/CommandPalette/paletteEvents";
import {
  CHAT_HISTORY_RAIL_ID,
  OPEN_NAV_RECORDS_EVENT,
  isChatPath,
} from "./chatHistoryRail";
import type { MinimalNavPane } from "./layoutModeStorage";
import MinimalRecordsHost from "./MinimalRecordsHost";
import SidebarCollapsedIconNav from "./SidebarCollapsedIconNav";
import SidebarMinimalPaneToggle from "./SidebarMinimalPaneToggle";
import { useChatSidebarOpen } from "../pages/Chat/hooks/useChatSidebarState";
import {
  isMacPlatform,
  railShortcutAria,
  railShortcutLabel,
} from "../utils/railShortcuts";
import { preferencesApi } from "../api/modules/preferences";
import { publicUrl } from "../utils/publicUrl";
import {
  COLLAPSED_WIDTH,
  EXPANDED_WIDTH,
  buildNavSections,
  navSectionLabel,
  type NavItem,
  type NavSection,
} from "./sidebarNav";
import { sectionsFromLayout, type SidebarNavLayout } from "./sidebarNavLayout";
import SidebarNavCustomizer from "./SidebarNavCustomizer";
import {
  chatThreadIdFromPath,
  isQuickChatSearch,
  useQuickChatActive,
} from "../pages/Chat/quickChatState";
import styles from "./Sidebar.module.less";
import { typeSize } from "../utils/mobileTypeScale";

const NAV_GROUPS_STORAGE_KEY = "octop:sidebar-nav-groups";
const LEGACY_COLLAPSED_GROUP_IDS: Record<string, string> = {
  "nav.settings": "settings",
  "nav.control": "control",
  "nav.admin": "admin",
};

function loadCollapsedGroups(): Set<string> {
  try {
    const raw = localStorage.getItem(NAV_GROUPS_STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return new Set(
        parsed
          .filter((x): x is string => typeof x === "string")
          .map((id) => LEGACY_COLLAPSED_GROUP_IDS[id] ?? id),
      );
    }
  } catch {
    /* ignore */
  }
  return new Set();
}

function saveCollapsedGroups(collapsed: Set<string>) {
  try {
    localStorage.setItem(
      NAV_GROUPS_STORAGE_KEY,
      JSON.stringify([...collapsed]),
    );
  } catch {
    /* ignore */
  }
}

function useNavGroupCollapse(navSections: NavSection[], selectedKey: string) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() =>
    loadCollapsedGroups(),
  );
  const activeGroupId = navSections.find(
    (section) =>
      section.id && section.items.some((item) => item.key === selectedKey),
  )?.id;

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      saveCollapsedGroups(next);
      return next;
    });
  }, []);

  const isGroupCollapsed = useCallback(
    (groupId: string) => collapsedGroups.has(groupId),
    [collapsedGroups],
  );

  useEffect(() => {
    if (!activeGroupId) return;
    setCollapsedGroups((prev) => {
      if (!prev.has(activeGroupId)) return prev;
      const next = new Set(prev);
      next.delete(activeGroupId);
      saveCollapsedGroups(next);
      return next;
    });
  }, [activeGroupId, selectedKey]);

  return { toggleGroup, isGroupCollapsed };
}

interface SidebarProps {
  selectedKey: string;
  collapsed: boolean;
  onToggle: () => void;
  isMobile?: boolean;
}

function historyRailLabels(
  t: TFunction<"translation", undefined>,
  open: boolean,
) {
  const label = open
    ? t("chat.collapseHistorySidebar", "收起对话历史")
    : t("chat.expandHistorySidebar", "展开对话历史");
  return {
    label,
    hint: `${label} (${railShortcutLabel("toggle-history", isMacPlatform())})`,
  };
}

function NavItemButton({
  item,
  active,
  isMobile,
  onNavigate,
  onToggleChatRail,
  showChatRailToggle,
  chatRailOpen,
  hasUpdate,
  t,
}: {
  item: NavItem;
  active: boolean;
  isMobile?: boolean;
  onNavigate: (path: string) => void;
  onToggleChatRail?: () => void;
  showChatRailToggle?: boolean;
  chatRailOpen?: boolean;
  hasUpdate: boolean;
  t: TFunction<"translation", undefined>;
}) {
  const showToggle = Boolean(
    showChatRailToggle && item.key === "chat" && onToggleChatRail,
  );
  const { label: railLabel, hint: railHint } = historyRailLabels(
    t,
    Boolean(chatRailOpen),
  );

  return (
    <div
      className={styles.navItemRow}
      style={{
        background: active ? "var(--fn-sidebar-item-active-bg)" : "transparent",
      }}
      onMouseEnter={(e) => {
        prefetchRoute(item.path);
        if (!active) {
          e.currentTarget.style.background = "var(--fn-sidebar-item-hover)";
        }
      }}
      onMouseLeave={(e) => {
        if (!active) {
          e.currentTarget.style.background = "transparent";
        }
      }}
    >
      <button
        type="button"
        className={styles.navItemMain}
        onClick={() => onNavigate(item.path)}
        style={{
          color: active
            ? "var(--fn-sidebar-item-active-text)"
            : "var(--fn-text-secondary)",
          fontSize: typeSize(14, isMobile),
          fontWeight: 400,
          paddingRight: showToggle ? 4 : 12,
        }}
      >
        <span
          style={{
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            color: active
              ? "var(--fn-sidebar-item-active-text)"
              : "var(--fn-text-tertiary)",
          }}
        >
          {item.icon}
        </span>
        <span
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            display: "flex",
            alignItems: "center",
            gap: 6,
            minWidth: 0,
          }}
        >
          {t(item.labelKey)}
          {item.key === "admin-advanced" && hasUpdate ? (
            <span className={styles.navUpdateBadge}>
              {t("nav.newVersionBadge", "有新版本")}
            </span>
          ) : null}
          {item.badge && (
            <span
              className="nav-badge-new"
              style={{
                fontSize: typeSize(9, isMobile),
                fontWeight: 600,
                padding: "1px 4px",
                borderRadius: "2px",
                whiteSpace: "nowrap",
                flexShrink: 0,
                textTransform: "uppercase",
                lineHeight: 1.2,
                letterSpacing: "0.5px",
              }}
            >
              {item.badge}
            </span>
          )}
        </span>
      </button>
      {showToggle ? (
        <button
          type="button"
          className={styles.chatRailExpandBtn}
          onClick={(e) => {
            e.stopPropagation();
            onToggleChatRail?.();
          }}
          aria-expanded={Boolean(chatRailOpen)}
          aria-label={railLabel}
          aria-keyshortcuts={railShortcutAria("toggle-history")}
          title={railHint}
        >
          <ArrowLeftRight size={14} strokeWidth={1.8} aria-hidden />
        </button>
      ) : null}
    </div>
  );
}

function NavList({
  sections,
  selectedKey,
  onNavigate,
  onToggleChatRail,
  showChatRailToggle,
  chatRailOpen,
  isMobile,
  isGroupCollapsed,
  toggleGroup,
  sectionFilter = "all",
  /** Group ids whose headers are omitted (items still render). */
  hideHeaderIds,
}: {
  sections: NavSection[];
  selectedKey: string;
  onNavigate: (path: string) => void;
  onToggleChatRail?: () => void;
  showChatRailToggle?: boolean;
  chatRailOpen?: boolean;
  isMobile?: boolean;
  isGroupCollapsed: (groupId: string) => boolean;
  toggleGroup: (groupId: string) => void;
  /** all = classic; primary = ungrouped; grouped = named groups */
  sectionFilter?: "all" | "primary" | "grouped";
  hideHeaderIds?: ReadonlySet<string>;
}) {
  const { t } = useTranslation();
  const { hasUpdate } = useUpdateStatus();
  const navSections = sections.filter((section) => {
    if (sectionFilter === "primary") return !section.id;
    if (sectionFilter === "grouped") return Boolean(section.id);
    return true;
  });

  const MOBILE_HIDDEN_KEYS = new Set<string>();

  return (
    <div
      style={{
        padding:
          sectionFilter === "grouped"
            ? "0 12px 8px"
            : sectionFilter === "primary"
            ? "8px 12px 0"
            : "8px 12px",
      }}
    >
      {navSections.map((section, sectionIndex) => {
        const visibleItems = isMobile
          ? section.items.filter((item) => !MOBILE_HIDDEN_KEYS.has(item.key))
          : section.items;
        if (visibleItems.length === 0) return null;

        const sectionKey = section.id ?? `flat-${sectionIndex}`;
        const hideHeader = Boolean(
          section.id && hideHeaderIds?.has(section.id),
        );
        const isFlat = !section.id || hideHeader;
        const groupCollapsed = section.id
          ? isGroupCollapsed(section.id)
          : false;

        if (isFlat) {
          return (
            <div key={sectionKey} className={styles.navGroup}>
              <div className={styles.navGroupItems}>
                {visibleItems.map((item) => (
                  <NavItemButton
                    key={item.key}
                    item={item}
                    active={selectedKey === item.key}
                    isMobile={isMobile}
                    onNavigate={onNavigate}
                    onToggleChatRail={onToggleChatRail}
                    showChatRailToggle={showChatRailToggle}
                    chatRailOpen={chatRailOpen}
                    hasUpdate={hasUpdate}
                    t={t}
                  />
                ))}
              </div>
            </div>
          );
        }

        return (
          <div key={sectionKey} className={styles.navGroup}>
            <button
              type="button"
              className={styles.navGroupHeader}
              onClick={() => toggleGroup(section.id!)}
              aria-expanded={!groupCollapsed}
            >
              <span className={styles.navGroupLabel}>
                {navSectionLabel(section, t)}
              </span>
              <ChevronDown
                size={12}
                strokeWidth={2}
                className={cx(
                  styles.navGroupChevron,
                  groupCollapsed && styles.navGroupChevronFolded,
                )}
                aria-hidden
              />
            </button>

            {!groupCollapsed && (
              <div className={styles.navGroupItems}>
                {visibleItems.map((item) => (
                  <NavItemButton
                    key={item.key}
                    item={item}
                    active={selectedKey === item.key}
                    isMobile={isMobile}
                    onNavigate={onNavigate}
                    onToggleChatRail={onToggleChatRail}
                    showChatRailToggle={showChatRailToggle}
                    chatRailOpen={chatRailOpen}
                    hasUpdate={hasUpdate}
                    t={t}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function Sidebar({
  selectedKey,
  collapsed,
  onToggle,
  isMobile,
}: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const drawerSwipeStart = useRef<{ x: number; y: number } | null>(null);
  const { name: baoName, tasks: baoTasks, appearance: baoLook } = useBao();
  const { isDark } = useTheme();
  const { hasUpdate } = useUpdateStatus();
  const { layoutMode, minimalPane, setMinimalPane } = useLayoutMode();
  const isMinimal = layoutMode === "minimal";
  const onChatPath = isChatPath(location.pathname);
  const [chatSidebarOpen, setChatSidebarOpen] = useChatSidebarOpen();
  const showChatRailToggle = !isMinimal;
  const chatRailOpen = showChatRailToggle && onChatPath && chatSidebarOpen;
  const catalog = useMemo(() => buildNavSections(), []);
  const [savedLayout, setSavedLayout] = useState<SidebarNavLayout | null>(null);
  const [customizerOpen, setCustomizerOpen] = useState(false);
  // Home and 快速对话 are pinned first-level entries: they are not part of the
  // customizable catalog, so a saved layout can never hide them and the
  // backend key list stays untouched.
  const customizerCatalog = useMemo(
    () =>
      catalog
        .map((section) => ({
          ...section,
          items: section.items.filter(
            (item) => item.key !== "home" && item.key !== "quick-chat",
          ),
        }))
        .filter((section) => section.items.length > 0),
    [catalog],
  );
  const navSections = useMemo(() => {
    const pinnedKeys = ["home", "quick-chat"];
    const allItems = catalog.flatMap((section) => section.items);
    const pinned = pinnedKeys
      .map((key) => allItems.find((item) => item.key === key))
      .filter((item): item is NavItem => Boolean(item));
    if (pinned.length === 0) return sectionsFromLayout(catalog, savedLayout);
    const sections = sectionsFromLayout(catalog, savedLayout)
      .map((section) => ({
        ...section,
        items: section.items.filter((item) => !pinnedKeys.includes(item.key)),
      }))
      .filter((section) => section.items.length > 0);
    const first = sections[0];
    if (first && !first.groupKey && !first.title) {
      const items = [...first.items];
      const home = pinned.find((item) => item.key === "home");
      const quick = pinned.find((item) => item.key === "quick-chat");
      if (quick) {
        const chatIndex = items.findIndex((item) => item.key === "chat");
        items.splice(chatIndex >= 0 ? chatIndex + 1 : 0, 0, quick);
      }
      if (home) items.unshift(home);
      return [{ ...first, items }, ...sections.slice(1)];
    }
    return [{ items: pinned }, ...sections];
  }, [catalog, savedLayout]);
  const quickThreadActive = useQuickChatActive(
    chatThreadIdFromPath(location.pathname),
  );
  // Quick chats live on the chat route; move the highlight to its own nav item.
  // ``?quick=1`` marks them in the URL, so the highlight is right immediately
  // and after a reload, before session metadata finishes loading.
  const quickChatActive =
    isQuickChatSearch(location.search) || quickThreadActive;
  const navSelectedKey = quickChatActive ? "quick-chat" : selectedKey;
  const { toggleGroup, isGroupCollapsed } = useNavGroupCollapse(
    navSections,
    navSelectedKey,
  );

  useEffect(() => {
    let cancelled = false;
    void preferencesApi
      .get()
      .then((prefs) => {
        if (!cancelled) setSavedLayout(prefs.sidebar_nav ?? null);
      })
      .catch(() => {
        /* keep the default nav */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const isRailCollapsed = collapsed && !isMobile;
  const desktopChrome = useDesktopChromeStyle();
  // macOS traffic lights sit above the brand; Windows already has its own
  // caption row, so the logo starts at the top of the rail.
  const reserveTrafficLightBand = desktopChrome === "mac";
  const wordmarkSrc = isDark
    ? publicUrl("logo_horizontal_white.png")
    : publicUrl("logo_horizontal_dark.png");

  const selectMinimalPane = useCallback(
    (pane: MinimalNavPane, opts?: { expand?: boolean }) => {
      setMinimalPane(pane);
      if (opts?.expand && collapsed) {
        onToggle();
      }
    },
    [collapsed, onToggle, setMinimalPane],
  );

  // Pane choice is user-controlled; do not flip 记录/设置 when the route changes.
  // Both records-open events map to the same pane switch in minimal mode.
  useEffect(() => {
    if (!isMinimal) return;
    const handler = () => {
      selectMinimalPane("records", { expand: true });
    };
    window.addEventListener(OPEN_NAV_RECORDS_EVENT, handler);
    window.addEventListener(EXPAND_CHAT_RAIL_EVENT, handler);
    return () => {
      window.removeEventListener(OPEN_NAV_RECORDS_EVENT, handler);
      window.removeEventListener(EXPAND_CHAT_RAIL_EVENT, handler);
    };
  }, [isMinimal, selectMinimalPane]);

  const handleNavigate = (path: string) => {
    // When navigating to /chat, preserve the current chatId in the URL so the
    // Chat component is not remounted (key stays the same) and the user stays
    // on their most recent conversation instead of seeing a blank welcome screen.
    // A quick chat is the exception: 快速对话 is a peer nav item, so 对话 must
    // leave quick mode instead of re-opening the same thread.
    if (
      path === "/chat" &&
      window.location.pathname.startsWith("/chat/") &&
      !quickChatActive
    ) {
      if (isMobile) onToggle();
      return;
    }
    navigate(path);
    if (isMobile) onToggle();
  };

  const brandInner = (
    <>
      <img
        src={isRailCollapsed ? publicUrl("logo_mark.svg") : wordmarkSrc}
        alt="HappyClaw"
        className={isRailCollapsed ? styles.brandMarkCollapsed : undefined}
        style={{
          height: isRailCollapsed ? 26 : isMobile ? 38 : 36,
          width: "auto",
          maxWidth: isRailCollapsed ? 36 : isMobile ? 190 : 160,
          objectFit: "contain",
          display: "block",
          flexShrink: 0,
        }}
      />
      {!isRailCollapsed && !isMobile && (
        /* Let the version badges shrink without squeezing the wordmark. */
        <div className={styles.brandMeta}>
          <CurrentVersionBadge isMobile={isMobile} />
          <AppVersionBadge isMobile={isMobile} />
        </div>
      )}
    </>
  );

  const soloActive = location.pathname === "/solo";

  const openSolo = () => {
    navigate("/solo");
    if (isMobile) onToggle();
  };

  // Quick chat is a first-level nav destination (see sidebarNav): the chat
  // page consumes ``?quick=1`` and opens the no-workspace conversation.

  const soloEntry = (
    <button
      type="button"
      className={cx(
        styles.soloEntry,
        isRailCollapsed && styles.soloEntryCollapsed,
        soloActive && styles.soloEntryActive,
      )}
      onClick={openSolo}
      aria-label={t("solo.openSolo")}
      aria-current={soloActive ? "page" : undefined}
      title={t("solo.openSolo")}
    >
      <SquareTerminal size={16} strokeWidth={1.8} />
      {!isRailCollapsed ? (
        <span className={styles.soloEntryLabel}>{t("solo.openSolo")}</span>
      ) : null}
    </button>
  );

  const baoRunning = baoTasks.filter(
    (task) => task.status === "running" || task.status === "awaiting",
  ).length;

  const openGlobalBao = () => {
    navigate("/bao");
    if (isMobile) onToggle();
  };

  // Global Bao is a first-class sidebar entry: always visible, keyboard
  // focusable, and it navigates to the cross-project page.
  const baoEntry = (
    <button
      type="button"
      className={cx(styles.soloEntry, isRailCollapsed && styles.soloEntryCollapsed)}
      onClick={openGlobalBao}
      aria-label={t("bao.entry.open")}
      aria-keyshortcuts="Alt+B"
      title={`${t("bao.entry.open")} (Alt+B)`}
    >
      <Mascot
        size={18}
        {...baoLook}
        color={mascotStatusInk(baoLook, baoRunning > 0 ? "working" : null)}
        state={baoRunning > 0 ? "working" : "idle"}
        className={styles.baoGlyph}
        surface="var(--fn-sidebar-bg)"
      />
      {!isRailCollapsed ? (
        <span className={styles.soloEntryLabel}>
          {t("bao.entry.labelNamed", { name: baoName })}
        </span>
      ) : null}
      {baoRunning > 0 ? (
        <span className={styles.baoBadge} aria-label={t("bao.entry.running", { count: baoRunning })}>
          {baoRunning}
        </span>
      ) : null}
    </button>
  );

  const userFooter = (
    <div
      className={styles.sidebarUser}
      style={{
        flexShrink: 0,
        // Collapsed avatar is centered, so its left gap is half the leftover
        // rail width. The same gap sits under it. 32px is `.accountAvatar`.
        padding: isRailCollapsed
          ? `10px 0 calc((max(${COLLAPSED_WIDTH}px, var(--window-controls-inset-start, 0px)) - 32px) / 2)`
          : "10px 12px",
        display: "flex",
        justifyContent: isRailCollapsed ? "center" : "stretch",
      }}
    >
      <AvatarDropdown
        placement="sidebar"
        compact={isRailCollapsed}
        onBeforeOpenSettings={isMobile && !collapsed ? onToggle : undefined}
        onCustomizeNav={() => setCustomizerOpen(true)}
      />
    </div>
  );

  const customizer = (
    <SidebarNavCustomizer
      open={customizerOpen}
      catalog={customizerCatalog}
      layout={savedLayout}
      onClose={() => setCustomizerOpen(false)}
      onSaved={setSavedLayout}
    />
  );

  const primaryItems = navSections.find((section) => !section.id)?.items ?? [];
  const namedSections = navSections.filter((section) => section.id);
  const firstNamed = namedSections[0];
  const settingsPaneLabel = firstNamed ? navSectionLabel(firstNamed, t) : null;
  const groupedItems = namedSections.flatMap((section) =>
    section.id && isGroupCollapsed(section.id) ? [] : section.items,
  );

  useEffect(() => {
    if (isMinimal && !settingsPaneLabel && minimalPane === "settings") {
      setMinimalPane("records");
    }
  }, [isMinimal, settingsPaneLabel, minimalPane, setMinimalPane]);

  const handleToggleChatRail = useCallback(() => {
    if (onChatPath && chatSidebarOpen) {
      setChatSidebarOpen(false);
      return;
    }
    window.dispatchEvent(new Event(EXPAND_CHAT_RAIL_EVENT));
    setChatSidebarOpen(true);
    if (!onChatPath) navigate("/chat");
  }, [chatSidebarOpen, navigate, onChatPath, setChatSidebarOpen]);

  const paneToggle = settingsPaneLabel ? (
    <SidebarMinimalPaneToggle
      settingsLabel={settingsPaneLabel}
      minimalPane={minimalPane}
      collapsed={isRailCollapsed}
      onSelect={selectMinimalPane}
    />
  ) : null;

  const classicNavBody = isRailCollapsed ? (
    <SidebarCollapsedIconNav
      items={navSections.flatMap((section) => {
        if (section.id && isGroupCollapsed(section.id)) {
          return [];
        }
        return section.items;
      })}
      selectedKey={navSelectedKey}
      onNavigate={handleNavigate}
      hasUpdate={hasUpdate}
      t={t}
    />
  ) : (
    <NavList
      sections={navSections}
      selectedKey={navSelectedKey}
      onNavigate={handleNavigate}
      onToggleChatRail={handleToggleChatRail}
      showChatRailToggle={showChatRailToggle}
      chatRailOpen={chatRailOpen}
      isMobile={isMobile}
      isGroupCollapsed={isGroupCollapsed}
      toggleGroup={toggleGroup}
    />
  );

  const minimalNavBody = (
    <div className={styles.minimalNavBody}>
      {isRailCollapsed ? (
        <div style={{ flexShrink: 0 }}>
          <SidebarCollapsedIconNav
            items={primaryItems}
            selectedKey={navSelectedKey}
            onNavigate={handleNavigate}
            hasUpdate={hasUpdate}
            t={t}
          />
          {paneToggle}
          {minimalPane === "settings" ? (
            <SidebarCollapsedIconNav
              items={groupedItems}
              selectedKey={navSelectedKey}
              onNavigate={handleNavigate}
              hasUpdate={hasUpdate}
              t={t}
            />
          ) : null}
        </div>
      ) : (
        <>
          <div className={styles.minimalPrimaryBlock}>
            <NavList
              sections={navSections}
              selectedKey={navSelectedKey}
              onNavigate={handleNavigate}
              isMobile={isMobile}
              isGroupCollapsed={isGroupCollapsed}
              toggleGroup={toggleGroup}
              sectionFilter="primary"
            />
            {paneToggle}
          </div>
          <div
            className={styles.minimalSettingsPane}
            hidden={minimalPane !== "settings"}
          >
            <NavList
              sections={navSections}
              selectedKey={navSelectedKey}
              onNavigate={handleNavigate}
              isMobile={isMobile}
              isGroupCollapsed={isGroupCollapsed}
              toggleGroup={toggleGroup}
              sectionFilter="grouped"
              hideHeaderIds={
                firstNamed?.id ? new Set([firstNamed.id]) : undefined
              }
            />
          </div>
        </>
      )}
      {/*
        Chat route: empty mount point — Chat portals live sessions here.
        Other routes: MinimalRecordsHost keeps expert/session nav available.
      */}
      <div
        id={CHAT_HISTORY_RAIL_ID}
        className={styles.minimalRecordsPane}
        hidden={isRailCollapsed || minimalPane !== "records"}
      >
        {!onChatPath ? <MinimalRecordsHost /> : null}
      </div>
    </div>
  );

  const navScrollBody = isMinimal ? minimalNavBody : classicNavBody;

  // Mobile: fixed overlay drawer
  if (isMobile) {
    return (
      <div
        className={styles.mobileDrawer}
        style={{
          position: "fixed",
          top: 0,
          bottom: 0,
          left: 0,
          height: "100%",
          width: "min(86vw, 320px)",
          boxSizing: "border-box",
          paddingLeft: "env(safe-area-inset-left, 0px)",
          background: "var(--fn-sidebar-bg)",
          borderRight: "1px solid var(--fn-sidebar-border)",
          zIndex: 100,
          display: "flex",
          flexDirection: "column",
          transform: collapsed ? "translateX(-100%)" : "translateX(0)",
          transition: "transform 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
          boxShadow: collapsed ? "none" : "4px 0 24px rgba(0, 0, 0, 0.14)",
        }}
        onTouchStart={(event) => {
          if (collapsed) return;
          const touch = event.touches[0];
          drawerSwipeStart.current = {
            x: touch.clientX,
            y: touch.clientY,
          };
        }}
        onTouchEnd={(event) => {
          const start = drawerSwipeStart.current;
          drawerSwipeStart.current = null;
          if (!start || collapsed) return;
          const touch = event.changedTouches[0];
          if (
            touch.clientX - start.x < -56 &&
            Math.abs(touch.clientY - start.y) < 64
          ) {
            onToggle();
          }
        }}
      >
        <div
          style={{
            // Match Header: iOS PWA draws under the status bar (#664).
            height: "calc(56px + env(safe-area-inset-top, 0px))",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "env(safe-area-inset-top, 0px) 12px 0 16px",
            boxSizing: "border-box",
            flexShrink: 0,
            gap: 8,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              minWidth: 0,
              flex: 1,
            }}
          >
            {brandInner}
          </div>
          <button
            type="button"
            onClick={onToggle}
            aria-label={t("nav.collapseSidebar")}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 40,
              height: 40,
              border: "none",
              borderRadius: "var(--fn-radius-md)",
              background: "transparent",
              color: "var(--fn-text-tertiary)",
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>

        {baoEntry}
        {soloEntry}

        <div
          style={{
            flex: 1,
            overflow:
              isMinimal && minimalPane === "records" ? "hidden" : "auto",
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          {navScrollBody}
        </div>

        <div
          style={{
            paddingBottom: "calc(8px + env(safe-area-inset-bottom, 0px))",
          }}
        >
          {userFooter}
          {customizer}
        </div>
      </div>
    );
  }

  // Desktop: custom sidebar with icon-only collapsed mode.
  // The trailing divider is MainLayout's RailEdgeControl, not a border here.
  return (
    <div className={styles.navRailHost}>
      <div
        className={styles.navRail}
        style={{
          width: isRailCollapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH,
          // On macOS the collapsed rail is the traffic-light column.
          // Icons, logo and footer center on it; the shell centers the
          // lights on the same line.
          minWidth: `max(${
            isRailCollapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH
          }px, var(--window-controls-inset-start, 0px))`,
          background: "var(--fn-sidebar-bg)",
          borderRight: "none",
          transition:
            "width 0.25s cubic-bezier(0.4, 0, 0.2, 1), min-width 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          flexShrink: 0,
          alignSelf: "stretch",
          minHeight: 0,
        }}
      >
        {/* macOS only: room for the traffic lights. Windows caption is a
            separate full-width row above the shell, so no blank here. */}
        {reserveTrafficLightBand ? (
          <div className={styles.navChrome} aria-hidden />
        ) : null}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            minWidth: 0,
            // Same top inset either way, so expanding only widens the bar.
            padding: isRailCollapsed ? "10px 0 12px" : "10px 8px 10px 14px",
            justifyContent: isRailCollapsed ? "center" : "flex-start",
            flexShrink: 0,
          }}
        >
          {brandInner}
        </div>
        {/* Discoverability for ⌘K: without a visible affordance the palette is
            only known to people who already knew the shortcut. */}
        <div style={{ padding: isRailCollapsed ? "0 8px 8px" : "0 10px 8px" }}>
          <button
            type="button"
            className={styles.paletteEntry}
            onClick={() =>
              window.dispatchEvent(new Event(SHELL_PALETTE_EVENT))
            }
            aria-label={t("palette.open", "搜索页面与操作")}
            title={t("palette.open", "搜索页面与操作")}
          >
            <Search size={14} strokeWidth={1.9} aria-hidden />
            {!isRailCollapsed ? (
              <>
                <span className={styles.paletteEntryLabel}>
                  {t("palette.open", "搜索页面与操作")}
                </span>
                <kbd className={styles.paletteEntryKbd}>
                  {isMacPlatform() ? "⌘K" : "Ctrl K"}
                </kbd>
              </>
            ) : null}
          </button>
        </div>
        {baoEntry}
        {soloEntry}
        <div
          className={isRailCollapsed ? styles.navScrollCollapsed : undefined}
          style={{
            flex: 1,
            minHeight: 0,
            overflowY:
              isMinimal && minimalPane === "records" ? "hidden" : "auto",
            overflowX: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {navScrollBody}
        </div>

        {userFooter}
        {customizer}
      </div>
    </div>
  );
}
