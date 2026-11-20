import { useCallback, useEffect, useRef, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import SessionList from "./SessionList";
import MinimalAgentSessionNav from "./MinimalAgentSessionNav";
import type { Session } from "../hooks/useSessions";
import type { OctopAgent } from "../../../context/AgentContext";
import RailEdgeControl from "../../../components/RailEdgeControl";
import { EXPAND_CHAT_RAIL_EVENT } from "../chatRailEvents";
import {
  isMacPlatform,
  railShortcutAria,
  railShortcutLabel,
} from "../../../utils/railShortcuts";
import styles from "../index.module.less";

interface ChatSidebarPanelProps {
  isMobile: boolean;
  sidebarOpen: boolean;
  sidebarWidth: number;
  isSidebarResizing?: boolean;
  sidebarElRef?: RefObject<HTMLDivElement>;
  agents: OctopAgent[];
  /** Owned experts that cannot chat yet — see ``SessionList.unreadyExperts``. */
  unreadyExperts?: number;
  sessions: Session[];
  activeThreadId: string | null;
  resolvedAgentId: string | null | undefined;
  sessionsHasMore: boolean;
  sessionsLoadingMore: boolean;
  onLoadMoreSessions: () => void;
  onFetchAllSessions: () => void;
  onSelectSession: (sessionId: string, agentId: string) => void;
  onAgentSelect: (agentId: string) => void;
  /** Start a fresh chat from an expert row (classic + minimal). */
  onNewChatWithAgent: (agentId: string, projectId?: string | null) => void;
  /** Open the folder picker that creates a workspace-backed project. */
  onNewProject?: () => void;
  onDeleteSession: (
    id: string,
    compact: boolean,
  ) => void | Promise<boolean | null | void>;
  onRenameSession: (id: string, name: string) => void;
  onPinSession: (id: string, pinned: boolean) => void;
  onForkSession: (id: string, agentId?: string | null) => void;
  forkDisabled?: boolean;
  forkDisabledHint?: string;
  onSidebarOpenChange: (open: boolean) => void;
  onSidebarResizeStart: (e: React.PointerEvent) => void;
  /** Mounted in MainLayout left rail (between app nav and content). */
  layoutRail?: boolean;
  /**
   * Minimal layout: render SessionList only inside the nav "records" pane
   * (no second rail chrome / mobile overlay).
   */
  navEmbedded?: boolean;
}

export default function ChatSidebarPanel({
  isMobile,
  sidebarOpen,
  sidebarWidth,
  isSidebarResizing = false,
  sidebarElRef,
  agents,
  unreadyExperts,
  sessions,
  activeThreadId,
  resolvedAgentId,
  sessionsHasMore,
  sessionsLoadingMore,
  onLoadMoreSessions,
  onFetchAllSessions,
  onSelectSession,
  onAgentSelect,
  onNewChatWithAgent,
  onNewProject,
  onDeleteSession,
  onRenameSession,
  onPinSession,
  onForkSession,
  forkDisabled,
  forkDisabledHint,
  onSidebarOpenChange,
  onSidebarResizeStart,
  layoutRail = false,
  navEmbedded = false,
}: ChatSidebarPanelProps) {
  const { t } = useTranslation();
  const swipeStart = useRef<{ x: number; y: number } | null>(null);

  // Native-feeling drawer dismissal: swipe the panel left.
  const handleDrawerTouchStart = (event: React.TouchEvent) => {
    if (!isMobile) return;
    const touch = event.touches[0];
    swipeStart.current = { x: touch.clientX, y: touch.clientY };
  };

  const handleDrawerTouchEnd = (event: React.TouchEvent) => {
    const start = swipeStart.current;
    swipeStart.current = null;
    if (!isMobile || !start) return;
    const touch = event.changedTouches[0];
    if (
      touch.clientX - start.x < -56 &&
      Math.abs(touch.clientY - start.y) < 64
    ) {
      onSidebarOpenChange(false);
    }
  };

  // A full-screen drawer must never be the first thing a phone shows. The open
  // preference is shared with the desktop rail, so a phone inheriting "open"
  // would land on the drawer instead of the conversation.
  const closedOnMobileRef = useRef(false);
  useEffect(() => {
    if (!isMobile || navEmbedded || closedOnMobileRef.current) return;
    closedOnMobileRef.current = true;
    if (sidebarOpen) onSidebarOpenChange(false);
  }, [isMobile, navEmbedded, onSidebarOpenChange, sidebarOpen]);

  // Native drawer opening: a right swipe from the left edge. The panel itself
  // handles swipe-left to dismiss; MainLayout excludes /chat from its own
  // drawer gesture, so the two never fight over the same edge.
  useEffect(() => {
    if (!isMobile || sidebarOpen || navEmbedded) return;
    let startX = 0;
    let startY = 0;
    let tracking = false;

    const onStart = (event: TouchEvent) => {
      if (event.touches.length !== 1) return;
      const touch = event.touches[0];
      if (touch.clientX > 24) return;
      tracking = true;
      startX = touch.clientX;
      startY = touch.clientY;
    };
    const onMove = (event: TouchEvent) => {
      if (!tracking) return;
      const touch = event.touches[0];
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;
      // Vertical scrolling wins the gesture as soon as it is clearly vertical.
      if (Math.abs(dy) > 40 && Math.abs(dy) >= Math.abs(dx)) {
        tracking = false;
        return;
      }
      if (dx > 56 && Math.abs(dy) < 40) {
        tracking = false;
        onSidebarOpenChange(true);
      }
    };
    const onEnd = () => {
      tracking = false;
    };

    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onEnd, { passive: true });
    return () => {
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onEnd);
    };
  }, [isMobile, navEmbedded, onSidebarOpenChange, sidebarOpen]);

  const handleRailToggle = useCallback(() => {
    if (sidebarOpen) {
      onSidebarOpenChange(false);
      return;
    }
    // MainLayout may also expand the nav when both rails were collapsed.
    window.dispatchEvent(new Event(EXPAND_CHAT_RAIL_EVENT));
    onSidebarOpenChange(true);
  }, [onSidebarOpenChange, sidebarOpen]);

  const historyLabel = t(
    sidebarOpen ? "chat.collapseHistorySidebar" : "chat.expandHistorySidebar",
    sidebarOpen ? "收起对话历史" : "展开对话历史",
  );
  const historyHint = `${historyLabel} (${railShortcutLabel(
    "toggle-history",
    isMacPlatform(),
  )})`;

  const sessionList = navEmbedded ? (
    <MinimalAgentSessionNav
      agents={agents}
      activeId={activeThreadId}
      activeAgentId={resolvedAgentId ?? null}
      activeSessions={sessions}
      onSelect={onSelectSession}
      onAgentSelect={onAgentSelect}
      onNewChat={onNewChatWithAgent}
      onNewProject={onNewProject}
      onDeleteActive={onDeleteSession}
      onRenameActive={onRenameSession}
      onPinActive={onPinSession}
      onFork={onForkSession}
      activeForkDisabled={forkDisabled}
      activeForkDisabledHint={forkDisabledHint}
      unreadyExperts={unreadyExperts}
    />
  ) : (
    <SessionList
      agents={agents}
      unreadyExperts={unreadyExperts}
      sessions={sessions}
      activeId={activeThreadId}
      activeAgentId={resolvedAgentId ?? null}
      hasMore={sessionsHasMore}
      loadingMore={sessionsLoadingMore}
      onLoadMore={onLoadMoreSessions}
      onFetchAllSessions={onFetchAllSessions}
      onSelect={onSelectSession}
      onAgentSelect={onAgentSelect}
      onNewChat={onNewChatWithAgent}
      onNewProject={onNewProject}
      onDelete={onDeleteSession}
      onRename={onRenameSession}
      onPin={onPinSession}
      onFork={onForkSession}
      activeForkDisabled={forkDisabled}
      activeForkDisabledHint={forkDisabledHint}
    />
  );

  if (navEmbedded) {
    return (
      <div className={styles.sidebarNavEmbedded} data-testid="chat-nav-records">
        {sessionList}
      </div>
    );
  }

  return (
    <div
      className={cx(
        styles.sidebarWrapper,
        layoutRail && styles.sidebarWrapperLayoutRail,
        !isMobile && !sidebarOpen && styles.sidebarWrapperCollapsed,
      )}
    >
      {isMobile && sidebarOpen && (
        <div
          className={styles.overlay}
          role="presentation"
          onClick={() => onSidebarOpenChange(false)}
        />
      )}

      <div
        ref={sidebarElRef}
        className={cx(
          styles.sidebar,
          sidebarOpen && styles.sidebarOpen,
          isSidebarResizing && styles.sidebarResizing,
        )}
        style={
          !isMobile && sidebarOpen
            ? { width: sidebarWidth, minWidth: sidebarWidth }
            : undefined
        }
        onTouchStart={handleDrawerTouchStart}
        onTouchEnd={handleDrawerTouchEnd}
      >
        {sessionList}
      </div>

      {!isMobile && sidebarOpen && (
        <RailEdgeControl
          expanded
          onToggle={handleRailToggle}
          side="end"
          showLine
          placement="center"
          className={styles.chatRailEdgeOpen}
          label={historyLabel}
          hint={historyHint}
          shortcut={railShortcutAria("toggle-history")}
          onResizeStart={onSidebarResizeStart}
          resizeLabel={t("chat.resizeSidebar", "调整侧栏宽度")}
        />
      )}
    </div>
  );
}
