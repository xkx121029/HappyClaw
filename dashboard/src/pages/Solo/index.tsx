import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import cx from "classnames";
import {
  ChevronDown,
  Command,
  FileCode2,
  Globe,
  Home,
  MessagesSquare,
  Minimize2,
  Minus,
  Moon,
  PanelLeft,
  PanelRight,
  PanelRightClose,
  Plus,
  Square,
  SquareTerminal,
  Sun,
  X,
} from "lucide-react";
import { useAgent } from "../../context/AgentContext";
import { useTheme } from "../../context/ThemeContext";
import { isAgentChatReady } from "../../utils/agentError";
import { useSessions } from "../Chat/hooks/useSessions";
import { useChat } from "../Chat/hooks/useChat";
import { useChatComposerResources } from "../Chat/hooks/useChatComposerResources";
import SoloConversationRail from "./components/SoloConversationRail";
import SoloChatPane from "./components/SoloChatPane";
import SoloEditorPane from "./components/SoloEditorPane";
import SoloRightPanel from "./components/SoloRightPanel";
import Splitter from "./components/Splitter";
import SoloMenu, { type SoloMenuItem } from "./components/SoloMenu";
import SoloCommandPalette, {
  type SoloCommandGroup,
} from "./components/SoloCommandPalette";
import {
  AGENT_MAX_WIDTH,
  AGENT_MIN_WIDTH,
  EDITOR_MIN_WIDTH,
  SIDE_MAX_WIDTH,
  SIDE_MIN_WIDTH,
  SPLITTER_GAP,
  TREE_MAX_WIDTH,
  TREE_MIN_WIDTH,
  fitWidths,
  useElementWidth,
  useSoloLayout,
} from "./hooks/useSoloLayout";
import styles from "./solo.module.less";

/** SOLO 的专家选中状态单独存放，和主模式（octop:active-agent）完全隔离。 */
const SOLO_AGENT_KEY = "octop:solo:active-agent";
/** 每个专家最后一次停留的会话，刷新后据此恢复时间线历史。 */
const SOLO_THREAD_KEY_PREFIX = "octop:solo:last-thread:";
/** 新会话还没写进后端时，先按专家记住上次选的模型。 */
const SOLO_MODEL_KEY_PREFIX = "octop:solo:model:";

/** 双击分栏条复位到参照稿的默认宽度。 */
const DEFAULT_SIDE_WIDTH = 215;
const DEFAULT_AGENT_WIDTH = 660;
const DEFAULT_TREE_WIDTH = 230;

function soloThreadKey(agentId: string): string {
  return `${SOLO_THREAD_KEY_PREFIX}${agentId}`;
}

function soloModelKey(agentId: string): string {
  return `${SOLO_MODEL_KEY_PREFIX}${agentId}`;
}

function readStoredThread(agentId: string | null): string | null {
  if (!agentId) return null;
  try {
    return localStorage.getItem(soloThreadKey(agentId));
  } catch {
    return null;
  }
}

function readStoredModel(agentId: string | null): string | null {
  if (!agentId) return null;
  try {
    return localStorage.getItem(soloModelKey(agentId));
  } catch {
    return null;
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function fileName(path: string): string {
  return path.replace(/\/+$/, "").split("/").pop() || path;
}

/** 状态栏语言名：按扩展名映射，未知一律 Plain Text。 */
function languageOf(path: string | null): string {
  if (!path) return "Plain Text";
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  switch (ext) {
    case "ts":
    case "tsx":
      return "TypeScript";
    case "js":
    case "jsx":
      return "JavaScript";
    case "json":
      return "JSON";
    case "md":
      return "Markdown";
    case "less":
    case "css":
      return "CSS";
    default:
      return "Plain Text";
  }
}

/**
 * SOLO 编程模式：独立全屏页面，按 TRAE SOLO 参照稿 1:1 还原。
 *
 * 纵向三段：顶栏（返回 / SOLO 标记 / 工具 / 页签 / 窗口按钮）+ 工作区
 * （会话栏 + 对话 + 编辑器与终端 + 文件树）+ 状态栏。会话、专家、模型全部
 * 复用现有后端接口，但专家与模型的选中状态和主模式互不共享。
 */
export default function SoloPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { agents, loading: agentsLoading, activeAgentId, refresh } = useAgent();
  const { isDark, toggle: toggleTheme } = useTheme();

  const workspaceRef = useRef<HTMLDivElement>(null);
  const workspaceWidth = useElementWidth(workspaceRef);
  const { layout, setPaneWidth, setTerminalRatio, setTimelineRatio } =
    useSoloLayout();

  const [soloAgentId, setSoloAgentId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(SOLO_AGENT_KEY);
    } catch {
      return null;
    }
  });
  const [threadId, setThreadId] = useState<string | null>(null);
  const [openFilePath, setOpenFilePath] = useState<string | null>(null);
  const [treeOverlayOpen, setTreeOverlayOpen] = useState(false);

  // 版式开关：折叠状态只影响结构，不改用户拖好的宽度。
  const [sideCollapsed, setSideCollapsed] = useState(false);
  const [agentCollapsed, setAgentCollapsed] = useState(false);
  const [treeHidden, setTreeHidden] = useState(false);
  const [editorView, setEditorView] = useState<"editor" | "browser">("editor");
  const [commandOpen, setCommandOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [agentMenuOpen, setAgentMenuOpen] = useState(false);
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);

  const soloAgent = useMemo(
    () => agents.find((agent) => agent.agent_id === soloAgentId) ?? null,
    [agents, soloAgentId],
  );
  const agentReady = isAgentChatReady(soloAgent?.state, soloAgent);

  useEffect(() => {
    void refresh({ silent: true });
  }, [refresh]);

  // 首次进入（或专家被删除）时落到主模式专家 / 第一个运行中的专家。
  useEffect(() => {
    if (agentsLoading || agents.length === 0) return;
    if (soloAgentId && agents.some((agent) => agent.agent_id === soloAgentId)) {
      return;
    }
    const preferred =
      agents.find((agent) => agent.agent_id === activeAgentId) ??
      agents.find((agent) => agent.state === "running") ??
      agents[0];
    setSoloAgentId(preferred.agent_id);
  }, [activeAgentId, agents, agentsLoading, soloAgentId]);

  useEffect(() => {
    if (!soloAgentId) return;
    try {
      localStorage.setItem(SOLO_AGENT_KEY, soloAgentId);
    } catch {
      // 隐私模式下写失败不影响使用
    }
  }, [soloAgentId]);

  // 刷新 / 切回专家时恢复上次停留的会话，时间线历史随之回放。
  useEffect(() => {
    setThreadId(readStoredThread(soloAgentId));
  }, [soloAgentId]);

  /** 切换会话时同步写入本地，保证刷新后还能回到同一轮行动记录。 */
  const selectThread = useCallback(
    (next: string | null) => {
      setThreadId(next);
      if (!soloAgentId) return;
      try {
        if (next) localStorage.setItem(soloThreadKey(soloAgentId), next);
        else localStorage.removeItem(soloThreadKey(soloAgentId));
      } catch {
        // 隐私模式下写失败不影响使用
      }
    },
    [soloAgentId],
  );

  const { sessions, loading: sessionsLoading, createSession } = useSessions(
    soloAgentId,
  );
  const chat = useChat(threadId, soloAgentId, false);

  // 会话的模型 / 推理设置由后端会话记录提供，主对话与 SOLO 因此看到同一个模型。
  const activeSession = useMemo(
    () => sessions.find((session) => session.threadId === threadId) ?? null,
    [sessions, threadId],
  );
  // 新会话还没有后端记录时，回落到本专家上次在 SOLO 里选的模型。
  const rememberedModel = useMemo(
    () => readStoredModel(soloAgentId),
    [soloAgentId, threadId],
  );
  const composer = useChatComposerResources(
    soloAgentId,
    threadId,
    activeSession?.modelRef ?? rememberedModel,
    activeSession?.reasoningMode,
    activeSession?.reasoningEffort,
    activeSession?.conversationMode,
    activeSession?.hitlPolicy,
    activeSession?.owned !== false,
  );

  // 用户选过的模型留一份本地记忆：没选会话时也能恢复，且不影响主模式的全局设置。
  useEffect(() => {
    if (!soloAgentId) return;
    try {
      if (composer.selectedModel) {
        localStorage.setItem(soloModelKey(soloAgentId), composer.selectedModel);
      } else {
        localStorage.removeItem(soloModelKey(soloAgentId));
      }
    } catch {
      // 隐私模式下写失败不影响使用
    }
  }, [composer.selectedModel, soloAgentId]);

  // 主对话靠 useChatNavigation 触发历史拉取；SOLO 没有那层导航，
  // 不显式调用的话刷新或往返后会话会显示成空的。
  useEffect(() => {
    if (!threadId || !soloAgentId) return;
    void chat.loadHistory(threadId);
  }, [chat.loadHistory, soloAgentId, threadId]);

  const handleSelectAgent = useCallback(
    (agentId: string) => {
      if (agentId === soloAgentId) return;
      setSoloAgentId(agentId);
      setOpenFilePath(null);
    },
    [soloAgentId],
  );

  // 折叠的栏位从宽度计算里让出来，编辑器立刻拿到那部分空间。
  const fitted = useMemo(
    () =>
      fitWidths(
        workspaceWidth,
        sideCollapsed ? 0 : layout.side,
        agentCollapsed ? 0 : layout.agent,
        layout.tree,
      ),
    [
      agentCollapsed,
      layout.agent,
      layout.side,
      layout.tree,
      sideCollapsed,
      workspaceWidth,
    ],
  );

  const treeVisible = fitted.tree > 0 && !treeHidden;
  const sideWidth = sideCollapsed ? 0 : fitted.side;
  const agentWidth = agentCollapsed ? 0 : fitted.agent;
  const treeWidth = treeVisible ? fitted.tree : 0;
  const splitterCount =
    (sideCollapsed ? 0 : 1) + (agentCollapsed ? 0 : 1) + (treeVisible ? 1 : 0);

  /** 拖拽上限：留给编辑器至少 EDITOR_MIN_WIDTH，分栏条按 1px 计。 */
  const editorBudget = useCallback(
    (extra: number) =>
      workspaceWidth -
      extra -
      splitterCount * SPLITTER_GAP -
      EDITOR_MIN_WIDTH,
    [splitterCount, workspaceWidth],
  );

  const handleSideDrag = useCallback(
    (delta: number) => {
      const maxSide = Math.min(
        SIDE_MAX_WIDTH,
        editorBudget(agentWidth + treeWidth),
      );
      setPaneWidth(
        "side",
        clamp(sideWidth + delta, SIDE_MIN_WIDTH, Math.max(SIDE_MIN_WIDTH, maxSide)),
      );
    },
    [agentWidth, editorBudget, setPaneWidth, sideWidth, treeWidth],
  );

  const handleAgentDrag = useCallback(
    (delta: number) => {
      const maxAgent = Math.min(
        AGENT_MAX_WIDTH,
        editorBudget(sideWidth + treeWidth),
      );
      setPaneWidth(
        "agent",
        clamp(
          agentWidth + delta,
          AGENT_MIN_WIDTH,
          Math.max(AGENT_MIN_WIDTH, maxAgent),
        ),
      );
    },
    [agentWidth, editorBudget, setPaneWidth, sideWidth, treeWidth],
  );

  const handleTreeDrag = useCallback(
    (delta: number) => {
      const maxTree = Math.min(
        TREE_MAX_WIDTH,
        editorBudget(sideWidth + agentWidth),
      );
      setPaneWidth(
        "tree",
        clamp(treeWidth - delta, TREE_MIN_WIDTH, Math.max(TREE_MIN_WIDTH, maxTree)),
      );
    },
    [agentWidth, editorBudget, setPaneWidth, sideWidth, treeWidth],
  );

  const resetSide = useCallback(
    () => setPaneWidth("side", DEFAULT_SIDE_WIDTH),
    [setPaneWidth],
  );
  const resetAgent = useCallback(
    () => setPaneWidth("agent", DEFAULT_AGENT_WIDTH),
    [setPaneWidth],
  );
  const resetTree = useCallback(
    () => setPaneWidth("tree", DEFAULT_TREE_WIDTH),
    [setPaneWidth],
  );

  const toggleTree = useCallback(() => {
    // 窄屏下文件树没有列位，只能用浮层。
    if (fitted.tree > 0) setTreeHidden((hidden) => !hidden);
    else setTreeOverlayOpen((open) => !open);
  }, [fitted.tree]);

  /** 侧栏「打开文件」：有列位就展开文件树，窄屏则开浮层。 */
  const openFiles = useCallback(() => {
    if (fitted.tree > 0) setTreeHidden(false);
    else setTreeOverlayOpen(true);
  }, [fitted.tree]);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
      return;
    }
    void document.documentElement.requestFullscreen().catch(() => {});
  }, []);

  // 用户的 Esc / F11 退出全屏也要同步图标。
  useEffect(() => {
    const handleChange = () =>
      setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", handleChange);
    handleChange();
    return () =>
      document.removeEventListener("fullscreenchange", handleChange);
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!event.ctrlKey || event.metaKey || event.shiftKey) return;
      const key = event.key.toLowerCase();
      if (event.altKey) {
        if (key !== "n") return;
        event.preventDefault();
        selectThread(null);
        return;
      }
      if (key === "b") {
        event.preventDefault();
        setSideCollapsed((collapsed) => !collapsed);
      } else if (key === "j") {
        event.preventDefault();
        setAgentCollapsed((collapsed) => !collapsed);
      } else if (key === "k") {
        event.preventDefault();
        setCommandOpen(true);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectThread]);

  const toolMenuItems: SoloMenuItem[] = [
    { key: "home", label: t("home.title") },
    { key: "editor", label: t("solo.editor") },
    { key: "browser", label: t("solo.browserTab") },
    { key: "terminal", label: t("solo.terminal") },
    { type: "separator" },
    { key: "newTask", label: t("solo.newTask") },
    {
      key: "toggleTree",
      label: t("solo.toggleTree"),
    },
    { key: "toggleAgent", label: t("solo.toggleAgent") },
    { key: "toggleTheme", label: t("solo.toggleTheme") },
  ];

  const handleToolMenuSelect = useCallback(
    (key: string) => {
      setToolsMenuOpen(false);
      switch (key) {
        case "home":
          selectThread(null);
          break;
        case "editor":
          setEditorView("editor");
          break;
        case "browser":
          setEditorView("browser");
          break;
        case "terminal":
          setEditorView("editor");
          setTerminalRatio(0.45);
          break;
        case "newTask":
          selectThread(null);
          break;
        case "toggleTree":
          toggleTree();
          break;
        case "toggleAgent":
          setAgentCollapsed((collapsed) => !collapsed);
          break;
        case "toggleTheme":
          toggleTheme();
          break;
        default:
          break;
      }
    },
    [selectThread, setTerminalRatio, toggleTheme, toggleTree],
  );

  const commandGroups: SoloCommandGroup[] = useMemo(
    () => [
      {
        label: t("solo.commands"),
        items: [
          { key: "cmd:newTask", label: t("solo.newTask"), hint: "Ctrl+Alt+N" },
          { key: "cmd:browser", label: t("solo.browserTab") },
          { key: "cmd:toggleTree", label: t("solo.toggleTree") },
          { key: "cmd:collapseSide", label: t("solo.collapseSide"), hint: "Ctrl+B" },
          { key: "cmd:toggleAgent", label: t("solo.toggleAgent"), hint: "Ctrl+J" },
          { key: "cmd:toggleTheme", label: t("solo.toggleTheme") },
        ],
      },
      {
        label: t("solo.expert"),
        items: agents.map((agent) => ({
          key: `agent:${agent.agent_id}`,
          label: agent.name,
        })),
      },
      {
        label: t("solo.sessions"),
        items: sessions.map((session) => ({
          key: `thread:${session.id}`,
          label: session.name,
        })),
      },
    ],
    [agents, sessions, t],
  );

  const runCommand = useCallback(
    (key: string) => {
      setCommandOpen(false);
      if (key.startsWith("agent:")) {
        handleSelectAgent(key.slice("agent:".length));
        return;
      }
      if (key.startsWith("thread:")) {
        selectThread(key.slice("thread:".length));
        return;
      }
      switch (key) {
        case "cmd:newTask":
          selectThread(null);
          break;
        case "cmd:browser":
          setEditorView("browser");
          break;
        case "cmd:toggleTree":
          toggleTree();
          break;
        case "cmd:collapseSide":
          setSideCollapsed((collapsed) => !collapsed);
          break;
        case "cmd:toggleAgent":
          setAgentCollapsed((collapsed) => !collapsed);
          break;
        case "cmd:toggleTheme":
          toggleTheme();
          break;
        default:
          break;
      }
    },
    [handleSelectAgent, selectThread, toggleTheme, toggleTree],
  );

  const agentMenuItems: SoloMenuItem[] = agents.map((agent) => ({
    key: agent.agent_id,
    label: agent.name,
    active: agent.agent_id === soloAgentId,
  }));

  return (
    <div className={styles.page}>
      <header className={styles.topbar} data-testid="solo-topbar">
        <button
          type="button"
          className={cx(
            styles.topbarLeft,
            sideCollapsed && styles.topbarLeftCollapsed,
          )}
          onClick={() => navigate("/chat")}
          title={t("solo.backToChat")}
          aria-label={t("solo.backToChat")}
        >
          <span className={styles.topbarBrand}>
            <SquareTerminal size={17} />
          </span>
          <span className={styles.topbarName}>SOLO</span>
        </button>

        <div className={styles.topbarMain}>
          <button
            type="button"
            className={styles.pbtn}
            onClick={() => setSideCollapsed((collapsed) => !collapsed)}
            title={`${t("solo.collapseSide")} (Ctrl+B)`}
            aria-label={t("solo.collapseSide")}
          >
            <PanelLeft size={15} />
          </button>

          <div
            className={styles.menuAnchor}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className={styles.projectSelect}
              onClick={() => setAgentMenuOpen((open) => !open)}
              title={t("solo.selectAgent")}
              aria-haspopup="menu"
              aria-expanded={agentMenuOpen}
            >
              <ChevronDown size={10} />
              <span className={styles.projectSelectName}>
                {soloAgent?.name ?? t("solo.noAgent")}
              </span>
            </button>
            {agentMenuOpen ? (
              <SoloMenu
                ariaLabel={t("solo.selectAgent")}
                items={agentMenuItems}
                onSelect={(key) => {
                  setAgentMenuOpen(false);
                  handleSelectAgent(key);
                }}
                onClose={() => setAgentMenuOpen(false)}
              />
            ) : null}
          </div>

          <button
            type="button"
            className={styles.pbtn}
            onClick={() => selectThread(null)}
            title={t("solo.newTask")}
            aria-label={t("solo.newTask")}
          >
            <Home size={15} />
          </button>

          <button
            type="button"
            className={styles.pbtn}
            onClick={() => setCommandOpen(true)}
            title={`${t("solo.commands")} (Ctrl+K)`}
            aria-label={t("solo.commands")}
          >
            <Command size={15} />
          </button>

          <button
            type="button"
            className={styles.pbtn}
            onClick={toggleTheme}
            title={t("solo.toggleTheme")}
            aria-label={t("solo.toggleTheme")}
          >
            {isDark ? <Sun size={15} /> : <Moon size={15} />}
          </button>

          <div className={styles.topbarDivider} />

          <div className={styles.topbarTabs}>
            {openFilePath ? (
              <div
                role="tab"
                aria-selected={editorView === "editor"}
                tabIndex={0}
                className={cx(
                  styles.workspaceTab,
                  editorView === "editor" && styles.workspaceTabActive,
                )}
                onClick={() => setEditorView("editor")}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setEditorView("editor");
                  }
                }}
                title={openFilePath}
              >
                <FileCode2 size={13} />
                <span>{fileName(openFilePath)}</span>
                {/* A nested button inside a button is invalid HTML and
                    unreachable by keyboard, so the tab is a div and the close
                    control is the real button. */}
                <button
                  type="button"
                  className={styles.workspaceTabClose}
                  title={t("solo.close")}
                  aria-label={t("solo.close")}
                  onClick={(event) => {
                    event.stopPropagation();
                    setOpenFilePath(null);
                  }}
                >
                  <X size={12} />
                </button>
              </div>
            ) : null}
            <button
              type="button"
              className={cx(
                styles.workspaceTab,
                editorView === "browser" && styles.workspaceTabActive,
              )}
              onClick={() => setEditorView("browser")}
            >
              <Globe size={13} />
              <span>{t("solo.browserTab")}</span>
            </button>
          </div>

          <div
            className={styles.menuAnchor}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className={styles.topbarAdd}
              onClick={() => setToolsMenuOpen((open) => !open)}
              title={t("solo.newTask")}
              aria-haspopup="menu"
              aria-expanded={toolsMenuOpen}
            >
              <Plus size={14} />
            </button>
            {toolsMenuOpen ? (
              <SoloMenu
                className={styles.toolsMenu}
                ariaLabel={t("solo.commands")}
                items={toolMenuItems}
                onSelect={handleToolMenuSelect}
                onClose={() => setToolsMenuOpen(false)}
              />
            ) : null}
          </div>

          <div className={styles.topbarRight}>
            <button
              type="button"
              className={cx(
                styles.layoutBtn,
                (treeVisible || treeOverlayOpen) && styles.layoutBtnActive,
              )}
              onClick={toggleTree}
              title={t("solo.toggleTree")}
              aria-label={t("solo.toggleTree")}
            >
              <PanelRight size={15} />
            </button>
            <button
              type="button"
              className={cx(
                styles.layoutBtn,
                !agentCollapsed && styles.layoutBtnActive,
              )}
              onClick={() => setAgentCollapsed((collapsed) => !collapsed)}
              title={t("solo.toggleAgent")}
              aria-label={t("solo.toggleAgent")}
            >
              {agentCollapsed ? (
                <MessagesSquare size={15} />
              ) : (
                <PanelRightClose size={15} />
              )}
            </button>
            <div className={styles.windowControls}>
              <button
                type="button"
                className={styles.windowButton}
                onClick={() => setSideCollapsed(true)}
                title={t("solo.minimize")}
                aria-label={t("solo.minimize")}
              >
                <Minus size={14} />
              </button>
              <button
                type="button"
                className={styles.windowButton}
                onClick={toggleFullscreen}
                title={t("solo.maximize")}
                aria-label={t("solo.maximize")}
              >
                {isFullscreen ? <Minimize2 size={13} /> : <Square size={13} />}
              </button>
              <button
                type="button"
                className={cx(styles.windowButton, styles.windowButtonClose)}
                onClick={() => navigate("/chat")}
                title={t("solo.close")}
                aria-label={t("solo.close")}
              >
                <X size={14} />
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className={styles.workspace} ref={workspaceRef}>
        {sideCollapsed ? null : (
          <>
            <div
              className={styles.sideSlot}
              style={{ width: fitted.side }}
              data-testid="solo-side"
            >
              <SoloConversationRail
                agents={agents}
                agentId={soloAgentId}
                agentReady={agentReady}
                onSelectAgent={handleSelectAgent}
                sessions={sessions}
                sessionsLoading={sessionsLoading}
                activeThreadId={threadId}
                onSelectThread={selectThread}
                onNewChat={() => selectThread(null)}
                onOpenFiles={openFiles}
                streaming={chat.isStreaming}
              />
            </div>
            <Splitter
              orientation="vertical"
              onDelta={handleSideDrag}
              onReset={resetSide}
              label={t("solo.resizeRail")}
              testId="solo-splitter-side"
            />
          </>
        )}

        {agentCollapsed ? null : (
          <>
            <div
              className={styles.agentPane}
              style={{ width: fitted.agent }}
              data-testid="solo-agent"
            >
              <SoloChatPane
                agentId={soloAgentId}
                activeAgent={soloAgent}
                agentReady={agentReady}
                threadId={threadId}
                onSelectThread={selectThread}
                createSession={createSession}
                chat={chat}
                composer={composer}
              />
            </div>
            <Splitter
              orientation="vertical"
              onDelta={handleAgentDrag}
              onReset={resetAgent}
              label={t("solo.resizeChat")}
              testId="solo-splitter-agent"
            />
          </>
        )}

        <div className={styles.mainColumn}>
          <SoloEditorPane
            agentId={soloAgentId}
            agentReady={agentReady}
            threadId={threadId}
            bridgeConnectionId={
              soloAgent?.bridge ? soloAgent.bridge_connection_id : null
            }
            filePath={openFilePath}
            onCloseFile={() => setOpenFilePath(null)}
            terminalRatio={layout.terminal}
            onTerminalRatioChange={setTerminalRatio}
            treeFitted={treeVisible}
            onToggleTree={toggleTree}
            view={editorView}
            onViewChange={setEditorView}
          />

          {treeOverlayOpen && !treeVisible ? (
            <div className={styles.rightOverlay}>
              <div className={styles.rightOverlayBar}>
                <button
                  type="button"
                  className={styles.overlayClose}
                  onClick={() => setTreeOverlayOpen(false)}
                  aria-label={t("solo.close")}
                >
                  <X size={14} />
                </button>
              </div>
              <SoloRightPanel
                agentId={soloAgentId}
                agentReady={agentReady}
                activePath={openFilePath}
                onOpenFile={(path) => {
                  setOpenFilePath(path);
                  setEditorView("editor");
                  setTreeOverlayOpen(false);
                }}
                onCloseFile={() => setOpenFilePath(null)}
                messages={chat.messages}
                isStreaming={chat.isStreaming}
                timelineRatio={layout.timeline}
                onTimelineRatioChange={setTimelineRatio}
              />
            </div>
          ) : null}
        </div>

        {treeVisible ? (
          <>
            <Splitter
              orientation="vertical"
              onDelta={handleTreeDrag}
              onReset={resetTree}
              label={t("solo.resizeFiles")}
              testId="solo-splitter-tree"
            />
            <div
              className={styles.treeSlot}
              style={{ width: fitted.tree }}
              data-testid="solo-tree"
            >
              <SoloRightPanel
                agentId={soloAgentId}
                agentReady={agentReady}
                activePath={openFilePath}
                onOpenFile={(path) => {
                  setOpenFilePath(path);
                  setEditorView("editor");
                }}
                onCloseFile={() => setOpenFilePath(null)}
                messages={chat.messages}
                isStreaming={chat.isStreaming}
                timelineRatio={layout.timeline}
                onTimelineRatioChange={setTimelineRatio}
              />
            </div>
          </>
        ) : null}
      </div>

      <footer className={styles.statusBar} data-testid="solo-statusbar">
        <div className={styles.statusGroup}>
          <span className={styles.statusItem}>main</span>
          <span className={styles.statusItem}>Ln 1, Col 1</span>
          <span className={styles.statusItem}>{languageOf(openFilePath)}</span>
        </div>
        <span className={styles.statusSpacer} />
        <div className={styles.statusGroup}>
          <span className={styles.statusItem}>UTF-8</span>
          <span className={styles.statusItem}>{t("solo.statusSpaces")}</span>
          <span className={styles.statusItem}>
            {isDark ? <Moon size={11} /> : <Sun size={11} />}
            {isDark ? t("solo.dark") : t("solo.light")}
          </span>
        </div>
      </footer>

      {commandOpen ? (
        <SoloCommandPalette
          groups={commandGroups}
          onClose={() => setCommandOpen(false)}
          onRun={runCommand}
        />
      ) : null}
    </div>
  );
}
