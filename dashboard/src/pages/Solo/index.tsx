import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { useAgent } from "../../context/AgentContext";
import { isAgentChatReady } from "../../utils/agentError";
import { useSessions } from "../Chat/hooks/useSessions";
import SoloConversationRail from "./components/SoloConversationRail";
import SoloChatPane from "./components/SoloChatPane";
import SoloEditorPane from "./components/SoloEditorPane";
import SoloFileTree from "./components/SoloFileTree";
import Splitter from "./components/Splitter";
import {
  CHAT_MAX_WIDTH,
  CHAT_MIN_WIDTH,
  RAIL_AUTO_COLLAPSE_WIDTH,
  RAIL_COLLAPSED_WIDTH,
  RAIL_MAX_WIDTH,
  RAIL_MIN_WIDTH,
  TREE_MAX_WIDTH,
  TREE_MIN_WIDTH,
  fitWidths,
  useElementWidth,
  useSoloLayout,
} from "./hooks/useSoloLayout";

/** 低于该宽度时强制收起选择器，并禁用展开按钮（避免图标栏里塞展开内容）。 */
const RAIL_HARD_COLLAPSE_WIDTH = 900;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
import styles from "./solo.module.less";

/**
 * SOLO 模式：会话选择器 / agent 对话 / 编辑器 + 终端 / 文件树。
 *
 * 数据层完全复用 /chat 与 workspace API：会话走 useSessions、消息走 useChat、
 * 文件走 workspaceApi，终端复用 Workbench 的终端 store。
 */
export default function SoloPage() {
  const { t } = useTranslation();
  const {
    agents,
    loading: agentsLoading,
    activeAgentId,
    activeAgent,
    setActiveAgent,
    refresh,
  } = useAgent();

  const pageRef = useRef<HTMLDivElement>(null);
  const pageWidth = useElementWidth(pageRef);
  const { layout, setPaneWidth, setTerminalRatio } = useSoloLayout();

  const [threadId, setThreadId] = useState<string | null>(null);
  const [openFilePath, setOpenFilePath] = useState<string | null>(null);
  /** null = 跟随容器宽度自动收起；true/false = 用户显式展开/收起。 */
  const [railExpanded, setRailExpanded] = useState<boolean | null>(null);
  const [treeOverlayOpen, setTreeOverlayOpen] = useState(false);

  const agentReady = isAgentChatReady(activeAgent?.state, activeAgent);
  const { sessions, loading: sessionsLoading, createSession } = useSessions(
    activeAgentId,
  );

  useEffect(() => {
    void refresh({ silent: true });
  }, [refresh]);

  useEffect(() => {
    if (activeAgentId || agentsLoading || agents.length === 0) return;
    const preferred = agents.find((agent) => agent.state === "running");
    setActiveAgent((preferred ?? agents[0]).agent_id);
  }, [activeAgentId, agents, agentsLoading, setActiveAgent]);

  // 切换专家后旧会话/旧文件都不再属于当前工作区，直接清空选择。
  const handleSelectAgent = useCallback(
    (agentId: string) => {
      if (agentId === activeAgentId) return;
      setThreadId(null);
      setOpenFilePath(null);
      setActiveAgent(agentId);
    },
    [activeAgentId, setActiveAgent],
  );

  const railLocked = pageWidth < RAIL_HARD_COLLAPSE_WIDTH;
  const autoCollapsed = pageWidth < RAIL_AUTO_COLLAPSE_WIDTH;
  const collapsed =
    railLocked || (railExpanded === null ? autoCollapsed : !railExpanded);
  const railWidth = collapsed
    ? RAIL_COLLAPSED_WIDTH
    : clamp(layout.rail, RAIL_MIN_WIDTH, RAIL_MAX_WIDTH);

  const fitted = useMemo(
    () => fitWidths(pageWidth, railWidth, layout.chat, layout.tree),
    [layout.chat, layout.tree, pageWidth, railWidth],
  );

  const chatWidth = collapsed ? fitted.chat : Math.max(fitted.chat, 0);
  const treeWidth = fitted.tree;

  const handleRailDrag = useCallback(
    (delta: number) => {
      setPaneWidth("rail", clamp(railWidth + delta, RAIL_MIN_WIDTH, RAIL_MAX_WIDTH));
    },
    [railWidth, setPaneWidth],
  );

  const handleChatDrag = useCallback(
    (delta: number) => {
      setPaneWidth("chat", clamp(fitted.chat + delta, CHAT_MIN_WIDTH, CHAT_MAX_WIDTH));
    },
    [fitted.chat, setPaneWidth],
  );

  const handleTreeDrag = useCallback(
    (delta: number) => {
      setPaneWidth("tree", clamp(treeWidth - delta, TREE_MIN_WIDTH, TREE_MAX_WIDTH));
    },
    [setPaneWidth, treeWidth],
  );

  const toggleRail = useCallback(() => {
    if (railLocked) return;
    setRailExpanded((previous) => !(previous === null ? autoCollapsed : !previous));
  }, [autoCollapsed, railLocked]);

  const treeToggle = useCallback(() => {
    setTreeOverlayOpen((open) => !open);
  }, []);

  return (
    <div className={styles.page} ref={pageRef}>
      <div className={styles.railSlot} style={{ width: railWidth }}>
        <SoloConversationRail
          agents={agents}
          activeAgentId={activeAgentId}
          onSelectAgent={handleSelectAgent}
          sessions={sessions}
          sessionsLoading={sessionsLoading}
          activeThreadId={threadId}
          onSelectThread={setThreadId}
          onNewChat={() => setThreadId(null)}
          collapsed={collapsed}
          toggleDisabled={railLocked}
          onToggleCollapsed={toggleRail}
        />
      </div>

      {!collapsed ? (
        <Splitter
          orientation="vertical"
          onDelta={handleRailDrag}
          label={t("solo.resizeRail")}
        />
      ) : null}

      <div className={styles.chatSlot} style={{ width: chatWidth }}>
        <SoloChatPane
          agentId={activeAgentId}
          threadId={threadId}
          onSelectThread={setThreadId}
          createSession={createSession}
        />
      </div>

      <Splitter
        orientation="vertical"
        onDelta={handleChatDrag}
        label={t("solo.resizeChat")}
      />

      <div className={styles.mainColumn}>
        <SoloEditorPane
          agentId={activeAgentId}
          agentReady={agentReady}
          filePath={openFilePath}
          onCloseFile={() => setOpenFilePath(null)}
          terminalRatio={layout.terminal}
          onTerminalRatioChange={setTerminalRatio}
          treeFitted={treeWidth > 0}
          onToggleTree={treeToggle}
        />
        {treeOverlayOpen && treeWidth === 0 ? (
          <div className={styles.treeOverlay}>
            <div className={styles.treeOverlayBar}>
              <button
                type="button"
                className={styles.treeOverlayClose}
                onClick={() => setTreeOverlayOpen(false)}
                aria-label={t("solo.closeFiles")}
              >
                <X size={14} />
              </button>
            </div>
            <SoloFileTree
              agentId={activeAgentId}
              agentReady={agentReady}
              activePath={openFilePath}
              onOpenFile={(path) => {
                setOpenFilePath(path);
                setTreeOverlayOpen(false);
              }}
            />
          </div>
        ) : null}
      </div>

      {treeWidth > 0 ? (
        <>
          <Splitter
            orientation="vertical"
            onDelta={handleTreeDrag}
            label={t("solo.resizeFiles")}
          />
          <div className={styles.treeSlot} style={{ width: treeWidth }}>
            <SoloFileTree
              agentId={activeAgentId}
              agentReady={agentReady}
              activePath={openFilePath}
              onOpenFile={setOpenFilePath}
            />
          </div>
        </>
      ) : null}
    </div>
  );
}
