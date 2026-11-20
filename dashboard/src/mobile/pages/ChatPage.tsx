import { useEffect, useMemo, useRef, useState } from "react";
import {
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import cx from "classnames";
import { useTranslation } from "react-i18next";

import { octopThreadsApi } from "../../api/modules/octopThreads";
import { useAgent, type OctopAgent } from "../../context/AgentContext";
import { useChat } from "../../pages/Chat/hooks/useChat";
import { useSessions, type Session } from "../../pages/Chat/hooks/useSessions";
import type { ChatMessage } from "../../pages/Chat/hooks/sseHelpers";
import { MobileAvatar } from "../components/MobileAvatar";
import { MobileChip, MobileDot } from "../components/MobileChip";
import { MobileComposer } from "../components/MobileComposer";
import { MobileEmpty } from "../components/MobileEmpty";
import { MobileIcon } from "../components/MobileIcon";
import { MobileSheet } from "../components/MobileSheet";
import { MobileSkeleton } from "../components/MobileSkeleton";
import { showMobileToast } from "../components/MobileToast";

/* ── helpers ───────────────────────────────────────────────────────────── */

function formatClock(timestamp: number): string {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

type Translate = (
  key: string,
  fallback: string,
  options?: Record<string, unknown>,
) => string;

function relativeTime(iso: string | null, t: Translate): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  if (diff < 60_000) return t("mobile.time.justNow", "刚刚");
  if (diff < 3_600_000)
    return t("mobile.time.minutesAgo", "{{n}} 分钟前", {
      n: Math.floor(diff / 60_000),
    });
  if (diff < 86_400_000)
    return t("mobile.time.hoursAgo", "{{n}} 小时前", {
      n: Math.floor(diff / 3_600_000),
    });
  if (diff < 7 * 86_400_000)
    return t("mobile.time.daysAgo", "{{n}} 天前", {
      n: Math.floor(diff / 86_400_000),
    });
  const date = new Date(then);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function readPendingText(state: unknown): string | null {
  if (!state || typeof state !== "object") return null;
  const value = (state as { pendingText?: unknown }).pendingText;
  return typeof value === "string" && value.trim() ? value : null;
}

/* ── message rendering ─────────────────────────────────────────────────── */

function MessageBubble({
  message,
  streaming,
  showMeta,
}: {
  message: ChatMessage;
  streaming: boolean;
  showMeta: boolean;
}) {
  const { t } = useTranslation();

  if (message.role === "system") {
    return <div className="m-msg m-msg--system">{message.content}</div>;
  }

  if (message.role === "tool") {
    const label =
      message.toolData?.displayName ||
      message.toolData?.name ||
      t("mobile.chat.toolCall", "工具调用");
    return (
      <div className="m-msg m-msg--assistant">
        <span className="m-tool-line">
          {message.status === "streaming" ? (
            <span className="m-spin" />
          ) : (
            <MobileIcon name="plug" size={13} />
          )}
          {label}
        </span>
      </div>
    );
  }

  const isUser = message.role === "user";
  const blocks = message.contentBlocks ?? [];
  const thinking = blocks
    .filter((block) => block.type === "thinking")
    .map((block) => block.content)
    .join("\n\n");
  const text =
    blocks
      .filter((block) => block.type === "text")
      .map((block) => block.content)
      .join("") || message.content;

  return (
    <div className={cx("m-msg", isUser ? "m-msg--user" : "m-msg--assistant")}>
      <div className={cx("m-bubble", message.status === "error" && "is-error")}>
        {thinking && !isUser ? (
          <details className="m-think">
            <summary>{t("mobile.chat.thinking", "思考过程")}</summary>
            <div className="m-think-body">{thinking}</div>
          </details>
        ) : null}
        {text}
        {message.status === "error"
          ? `\n${t(
              "mobile.chat.generationFailed",
              "生成失败，请重试或检查专家状态。",
            )}`
          : null}
        {streaming ? <span className="m-cursor" /> : null}
        {message.attachments?.length
          ? message.attachments.map((attachment, index) => (
              <span
                className="m-msg-attachment"
                key={`${attachment.filename ?? "file"}-${index}`}
              >
                <MobileIcon
                  name={attachment.kind === "image" ? "spark" : "book"}
                  size={12}
                />
                {attachment.filename ?? t("mobile.chat.attachment", "附件")}
              </span>
            ))
          : null}
      </div>
      {showMeta ? (
        <div className="m-msg-meta">{formatClock(message.timestamp)}</div>
      ) : null}
    </div>
  );
}

function Welcome({
  agent,
  quick,
  onPrompt,
  prompts,
}: {
  agent: OctopAgent | null;
  quick: boolean;
  onPrompt: (text: string) => void;
  prompts: string[];
}) {
  const { t } = useTranslation();
  return (
    <div className="m-welcome">
      <div className="m-welcome-top">
        <MobileAvatar
          name={agent?.name ?? t("mobile.chat.expertFallback", "专家")}
          src={agent?.icon_url}
          color={agent?.color}
          size={52}
          square
        />
        <div className="m-grow">
          <div className="m-welcome-name">
            {agent?.name ?? t("mobile.chat.noExpert", "还没有可用专家")}
          </div>
          <div className="m-welcome-desc">
            {quick
              ? t(
                  "mobile.chat.quickWelcomeDesc",
                  "轻量开聊，不使用工作区，文件类工具已隐藏。",
                )
              : agent?.description ||
                (agent
                  ? t(
                      "mobile.chat.chatWelcomeDesc",
                      "直接开始对话，随时切换话题。",
                    )
                  : t(
                      "mobile.chat.noExpertWelcomeDesc",
                      "请先在桌面端启动一个专家，再回到这里。",
                    ))}
          </div>
        </div>
      </div>
      {agent ? (
        <div className="m-stack">
          {prompts.map((prompt) => (
            <button
              type="button"
              key={prompt}
              className="m-prompt"
              onClick={() => onPrompt(prompt)}
            >
              <MobileIcon name="spark" size={17} />
              <span className="m-grow">{prompt}</span>
              <MobileIcon name="chevron" size={15} />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/* ── chat surface (shared by /m/chat and /m/quick) ─────────────────────── */

interface ChatSurfaceProps {
  agentId: string;
  agent: OctopAgent | null;
  threadId: string | null;
  mode: "chat" | "quick";
  onOpenThread: (threadId: string) => void;
  onNewThread: () => void;
  onCreateAndSend?: (text: string) => Promise<void>;
  onBack?: () => void;
  showSessions?: boolean;
  pendingText?: string | null;
  onPendingConsumed?: () => void;
}

function ChatSurface({
  agentId,
  agent,
  threadId,
  mode,
  onOpenThread,
  onNewThread,
  onCreateAndSend,
  onBack,
  showSessions = false,
  pendingText = null,
  onPendingConsumed,
}: ChatSurfaceProps) {
  const { t } = useTranslation();
  const {
    sessions,
    loading: sessionsLoading,
    deleteSession,
    renameSession,
    fetchSessions,
  } = useSessions(agentId);
  const chat = useChat(threadId, agentId, false);

  const [draft, setDraft] = useState("");
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [actionSession, setActionSession] = useState<Session | null>(null);
  const [renameTarget, setRenameTarget] = useState<Session | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null);
  const [showJump, setShowJump] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const pressTimer = useRef<number | null>(null);
  const longPressed = useRef(false);
  const consumedRef = useRef<string | null>(null);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === threadId) ?? null,
    [sessions, threadId],
  );
  const isQuick = mode === "quick" || Boolean(activeSession?.quickChat);

  // Hydrate the visible thread and keep the session list fresh.
  useEffect(() => {
    void chat.loadHistory(threadId ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, agentId]);

  useEffect(() => {
    void fetchSessions(threadId ?? undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  // Consume a message queued while the thread was being created.
  useEffect(() => {
    if (!pendingText || !threadId) return;
    if (consumedRef.current === threadId) return;
    consumedRef.current = threadId;
    chat.sendMessage(
      pendingText,
      "",
      agentId,
      undefined,
      threadId,
      null,
      null,
      null,
      null,
      undefined,
      "auto",
      null,
      "craft",
      null,
    );
    onPendingConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingText, threadId, agentId]);

  const scrollToBottom = (smooth = false) => {
    const element = scrollRef.current;
    if (!element) return;
    element.scrollTo({
      top: element.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
  };

  useEffect(() => {
    if (stickRef.current) scrollToBottom();
  }, [chat.messages, chat.isStreaming]);

  useEffect(() => {
    if (!chat.historyLoading) {
      stickRef.current = true;
      scrollToBottom();
    }
  }, [chat.historyLoading, threadId]);

  const handleScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const atBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight < 56;
    stickRef.current = atBottom;
    setShowJump(!atBottom && chat.messages.length > 0);
  };

  const sendText = async (text: string) => {
    const clean = text.trim();
    if (!clean) return;
    setDraft("");
    if (threadId) {
      chat.sendMessage(
        clean,
        "",
        agentId,
        undefined,
        threadId,
        null,
        null,
        null,
        null,
        undefined,
        "auto",
        null,
        "craft",
        null,
      );
      return;
    }
    if (!onCreateAndSend) return;
    try {
      await onCreateAndSend(clean);
    } catch {
      setDraft(clean);
      showMobileToast(t("mobile.chat.createFailed", "创建会话失败，请重试"));
    }
  };

  const prompts = useMemo(() => {
    const welcome = agent?.welcome_message?.trim();
    if (welcome) {
      const lines = welcome
        .split(/\n+/)
        .map((line) => line.replace(/^[-*·\d.\s]+/, "").trim())
        .filter((line) => line.length >= 4 && line.length <= 60);
      if (lines.length >= 2) return lines.slice(0, 3);
    }
    return [
      t("mobile.chat.defaultPrompt1", "帮我梳理今天的任务"),
      t("mobile.chat.defaultPrompt2", "解释一个概念"),
      t("mobile.chat.defaultPrompt3", "写一封邮件"),
    ];
  }, [agent?.welcome_message, t]);

  const startPress = (session: Session) => {
    longPressed.current = false;
    pressTimer.current = window.setTimeout(() => {
      longPressed.current = true;
      setActionSession(session);
    }, 480);
  };
  const cancelPress = () => {
    if (pressTimer.current) {
      window.clearTimeout(pressTimer.current);
      pressTimer.current = null;
    }
  };

  const messages = chat.messages;
  const lastIndex = messages.length - 1;

  return (
    <div className="m-chat">
      <header className="m-chat-head">
        {onBack ? (
          <button
            type="button"
            className="m-iconbtn"
            aria-label={t("common.back", "返回")}
            onClick={onBack}
          >
            <MobileIcon name="back" />
          </button>
        ) : (
          <span style={{ width: 8 }} />
        )}
        <div className="m-chat-head-main">
          <div className="m-chat-head-name">
            {agent?.name ?? t("mobile.chat.chatTitle", "对话")}
          </div>
          {isQuick ? (
            <div className="m-chat-head-sub">
              {t("mobile.chat.quickSub", "快速对话 · 不使用工作区")}
            </div>
          ) : null}
        </div>
        <div className="m-rowflex">
          {showSessions ? (
            <button
              type="button"
              className="m-iconbtn"
              aria-label={t("mobile.chat.sessionList", "会话列表")}
              onClick={() => setSessionsOpen(true)}
            >
              <MobileIcon name="list" />
            </button>
          ) : null}
          <button
            type="button"
            className="m-iconbtn"
            aria-label={t("mobile.chat.newChat", "新对话")}
            onClick={onNewThread}
          >
            <MobileIcon name="plus" />
          </button>
        </div>
      </header>

      <div
        className="m-chat-scroll"
        ref={scrollRef}
        onScroll={handleScroll}
        data-testid="m-chat-scroll"
      >
        {messages.length === 0 && !chat.historyLoading ? (
          <Welcome
            agent={agent}
            quick={isQuick}
            onPrompt={(text) => void sendText(text)}
            prompts={prompts}
          />
        ) : (
          <>
            {chat.historyHasMore ? (
              <button
                type="button"
                className="m-linkbtn"
                style={{ alignSelf: "center" }}
                onClick={() => void chat.loadMoreHistory()}
              >
                {t("mobile.chat.loadEarlier", "加载更早的消息")}
              </button>
            ) : null}
            {chat.historyLoading ? <MobileSkeleton rows={3} /> : null}
            {chat.historyError ? (
              <div className="m-empty" style={{ padding: "24px 0" }}>
                <div className="m-empty-desc">
                  {t("mobile.chat.historyFailed", "历史消息加载失败")}
                </div>
                <button
                  type="button"
                  className="m-btn"
                  onClick={() => void chat.retryHistory()}
                >
                  {t("common.retry", "重试")}
                </button>
              </div>
            ) : null}
            {messages.map((message, index) => {
              const next = messages[index + 1];
              const showMeta = !next || next.role !== message.role;
              return (
                <MessageBubble
                  key={message.id}
                  message={message}
                  streaming={
                    chat.isStreaming &&
                    index === lastIndex &&
                    message.role === "assistant"
                  }
                  showMeta={showMeta}
                />
              );
            })}
            {chat.isStreaming ? (
              <div className="m-chat-status">
                <span className="m-spin" />
                {t("mobile.chat.generating", "正在生成…")}
              </div>
            ) : null}
          </>
        )}
      </div>

      {showJump ? (
        <button
          type="button"
          className="m-jump-bottom"
          aria-label={t("mobile.chat.backToBottom", "回到底部")}
          onClick={() => {
            stickRef.current = true;
            setShowJump(false);
            scrollToBottom(true);
          }}
        >
          <MobileIcon
            name="chevron"
            size={18}
            style={{ transform: "rotate(90deg)" }}
          />
        </button>
      ) : null}

      <MobileComposer
        value={draft}
        onChange={setDraft}
        onSend={() => void sendText(draft)}
        onStop={() => chat.cancelStream()}
        streaming={chat.isStreaming}
        placeholder={
          isQuick
            ? t("mobile.chat.quickPlaceholder", "快速提问…")
            : t("mobile.composer.placeholder", "发消息…")
        }
        hint={
          isQuick
            ? t("mobile.chat.quickHint", "快速对话不使用工作区")
            : undefined
        }
      />

      {showSessions ? (
        <MobileSheet
          open={sessionsOpen}
          title={t("mobile.chat.sessionsTitle", "对话")}
          height="half"
          onClose={() => setSessionsOpen(false)}
        >
          <div className="m-sheet-actions">
            <button
              type="button"
              className="m-sheet-action"
              onClick={() => {
                setSessionsOpen(false);
                onNewThread();
              }}
            >
              <MobileIcon name="plus" size={18} />
              {t("mobile.chat.newChat", "新对话")}
            </button>
          </div>
          {sessionsLoading && sessions.length === 0 ? (
            <MobileSkeleton rows={3} />
          ) : sessions.length === 0 ? (
            <MobileEmpty
              icon="chat"
              title={t("mobile.chat.noChats", "还没有对话")}
            />
          ) : (
            <div className="m-group">
              {sessions.map((session) => (
                <button
                  type="button"
                  key={session.id}
                  className="m-row"
                  onPointerDown={() => startPress(session)}
                  onPointerUp={cancelPress}
                  onPointerLeave={cancelPress}
                  onPointerCancel={cancelPress}
                  onClick={() => {
                    if (longPressed.current) {
                      longPressed.current = false;
                      return;
                    }
                    setSessionsOpen(false);
                    onOpenThread(session.id);
                  }}
                >
                  <span className="m-row-main">
                    <span className="m-row-title">
                      {session.turnActive ? <MobileDot tone="ok" /> : null}
                      {session.awaitingUser ? <MobileDot tone="warn" /> : null}
                      {session.name}
                    </span>
                    <span className="m-row-sub">
                      {relativeTime(session.updatedAt, t)}
                    </span>
                  </span>
                  {session.quickChat ? (
                    <MobileChip tone="accent">
                      {t("mobile.chat.quickChip", "快速")}
                    </MobileChip>
                  ) : null}
                  {session.id === threadId ? (
                    <MobileIcon name="check" size={16} />
                  ) : null}
                </button>
              ))}
            </div>
          )}
        </MobileSheet>
      ) : null}

      <MobileSheet
        open={Boolean(actionSession)}
        title={actionSession?.name}
        onClose={() => setActionSession(null)}
      >
        <div className="m-sheet-actions">
          <button
            type="button"
            className="m-sheet-action"
            onClick={() => {
              if (!actionSession) return;
              setRenameValue(actionSession.name);
              setRenameTarget(actionSession);
              setActionSession(null);
            }}
          >
            <MobileIcon name="edit" size={18} />
            {t("common.rename", "重命名")}
          </button>
          <button
            type="button"
            className="m-sheet-action is-danger"
            onClick={() => {
              setDeleteTarget(actionSession);
              setActionSession(null);
            }}
          >
            <MobileIcon name="trash" size={18} />
            {t("mobile.chat.deleteChat", "删除对话")}
          </button>
        </div>
      </MobileSheet>

      <MobileSheet
        open={Boolean(renameTarget)}
        title={t("mobile.chat.renameTitle", "重命名对话")}
        onClose={() => setRenameTarget(null)}
      >
        <div className="m-search">
          <input
            value={renameValue}
            autoFocus
            onChange={(event) => setRenameValue(event.target.value)}
            placeholder={t("mobile.chat.renamePlaceholder", "对话名称")}
          />
        </div>
        <div className="m-stack m-mt16">
          <button
            type="button"
            className="m-btn m-btn--primary m-btn--block"
            disabled={!renameValue.trim()}
            onClick={() => {
              if (!renameTarget) return;
              renameSession(renameTarget.id, renameValue);
              setRenameTarget(null);
            }}
          >
            {t("common.save", "保存")}
          </button>
        </div>
      </MobileSheet>

      <MobileSheet
        open={Boolean(deleteTarget)}
        title={t("mobile.chat.deleteChat", "删除对话")}
        onClose={() => setDeleteTarget(null)}
      >
        <p className="m-hint">
          {t(
            "mobile.chat.deleteConfirm",
            "删除后无法恢复。确定删除「{{name}}」吗？",
            {
              name: deleteTarget?.name ?? "",
            },
          )}
        </p>
        <div className="m-stack m-mt16">
          <button
            type="button"
            className="m-btn m-btn--block"
            style={{ color: "var(--m-danger)" }}
            onClick={async () => {
              if (!deleteTarget) return;
              const target = deleteTarget;
              setDeleteTarget(null);
              try {
                const result = await deleteSession(target.id, false);
                if (result === false)
                  showMobileToast(t("common.deleteFailed", "删除失败"));
                else if (target.id === threadId) onOpenThread("");
              } catch {
                showMobileToast(t("common.deleteFailed", "删除失败"));
              }
            }}
          >
            {t("common.delete", "删除")}
          </button>
          <button
            type="button"
            className="m-btn m-btn--block"
            onClick={() => setDeleteTarget(null)}
          >
            {t("common.cancel", "取消")}
          </button>
        </div>
      </MobileSheet>
    </div>
  );
}

/* ── /m/chat ───────────────────────────────────────────────────────────── */

export function ChatPage() {
  const { t } = useTranslation();
  const { agentId: routeAgentId, threadId: routeThreadId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { agents, activeAgentId, loading } = useAgent();
  const agentId = routeAgentId ?? activeAgentId ?? null;

  const quickFlag = new URLSearchParams(location.search).get("quick");
  useEffect(() => {
    if (quickFlag === "1") navigate("/m/quick", { replace: true });
  }, [quickFlag, navigate]);

  useEffect(() => {
    if (!agentId) return;
    if (!routeAgentId) {
      navigate(`/m/chat/${agentId}`, { replace: true });
      return;
    }
    if (routeThreadId) return;
  }, [agentId, routeAgentId, routeThreadId, navigate]);

  const handleNewThread = async () => {
    if (!agentId) return;
    const created = octopThreadsApi.create(agentId);
    try {
      const result = await created;
      navigate(`/m/chat/${agentId}/${result.thread_id}`);
    } catch {
      showMobileToast(t("mobile.chat.createFailed", "创建会话失败，请重试"));
    }
  };

  const agent = agents.find((item) => item.agent_id === agentId) ?? null;
  const pendingText = readPendingText(location.state);

  if (!agentId) {
    return (
      <div className="m-chat">
        {loading ? (
          <div className="m-page" style={{ paddingTop: 24 }}>
            <MobileSkeleton rows={3} />
          </div>
        ) : (
          <MobileEmpty
            icon="experts"
            title={t("mobile.chat.noExpert", "还没有可用专家")}
            description={t(
              "mobile.chat.noExpertDesc",
              "请先在桌面端启动一个专家，再回到手机端对话。",
            )}
          />
        )}
      </div>
    );
  }

  return (
    <ChatSurface
      key={`${agentId}`}
      agentId={agentId}
      agent={agent}
      threadId={routeThreadId ?? null}
      mode="chat"
      onOpenThread={(threadId) =>
        navigate(
          threadId ? `/m/chat/${agentId}/${threadId}` : `/m/chat/${agentId}`,
        )
      }
      onNewThread={() => void handleNewThread()}
      onCreateAndSend={async (text) => {
        const created = await octopThreadsApi.create(agentId);
        navigate(`/m/chat/${agentId}/${created.thread_id}`, {
          state: { pendingText: text },
        });
      }}
      onBack={() =>
        routeThreadId
          ? navigate(`/m/chat/${agentId}`, { replace: true })
          : navigate("/m/home")
      }
      showSessions
      pendingText={pendingText}
      onPendingConsumed={() =>
        navigate(`${location.pathname}${location.search}`, {
          replace: true,
          state: null,
        })
      }
    />
  );
}

/* ── /m/quick (first-class tab) ────────────────────────────────────────── */

export function QuickChatPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { agents, activeAgentId, loading } = useAgent();

  const quickAgent = useMemo(() => {
    const happy = agents.find(
      (item) =>
        item.template_name === "happyclaw" || item.agent_id === "happyclaw",
    );
    if (happy) return happy;
    return (
      agents.find((item) => item.agent_id === activeAgentId) ??
      agents.find((item) => item.state === "running") ??
      agents[0] ??
      null
    );
  }, [agents, activeAgentId]);

  const agentId = quickAgent?.agent_id ?? null;
  const threadParam = searchParams.get("thread");
  const [threadId, setThreadId] = useState<string | null>(threadParam);
  const creatingRef = useRef(false);
  const { sessions, loading: sessionsLoading } = useSessions(agentId);

  useEffect(() => {
    setThreadId(threadParam);
  }, [threadParam]);

  useEffect(() => {
    if (!agentId || threadId || sessionsLoading || creatingRef.current) return;
    const latestQuick = sessions.find((session) => session.quickChat);
    if (latestQuick) {
      setThreadId(latestQuick.id);
      setSearchParams({ thread: latestQuick.id }, { replace: true });
      return;
    }
    creatingRef.current = true;
    void octopThreadsApi
      .createQuick(agentId)
      .then((created) => {
        setThreadId(created.thread_id);
        setSearchParams({ thread: created.thread_id }, { replace: true });
      })
      .catch(() =>
        showMobileToast(
          t("mobile.chat.quickCreateFailed", "快速对话创建失败，请稍后重试"),
        ),
      )
      .finally(() => {
        creatingRef.current = false;
      });
  }, [agentId, threadId, sessionsLoading, sessions, setSearchParams, t]);

  const handleNewThread = async () => {
    if (!agentId) return;
    try {
      const created = await octopThreadsApi.createQuick(agentId);
      setThreadId(created.thread_id);
      setSearchParams({ thread: created.thread_id }, { replace: true });
    } catch {
      showMobileToast(
        t("mobile.chat.quickCreateFailed", "快速对话创建失败，请稍后重试"),
      );
    }
  };

  const pendingText = readPendingText(location.state);

  if (!agentId) {
    return (
      <div className="m-chat">
        {loading || sessionsLoading ? (
          <div className="m-page" style={{ paddingTop: 24 }}>
            <MobileSkeleton rows={3} />
          </div>
        ) : (
          <MobileEmpty
            icon="zap"
            title={t("mobile.chat.noExpert", "还没有可用专家")}
            description={t(
              "mobile.chat.quickNoExpertDesc",
              "快速对话需要一个运行中的专家，请先在桌面端启动。",
            )}
          />
        )}
      </div>
    );
  }

  return (
    <ChatSurface
      key={`quick-${agentId}`}
      agentId={agentId}
      agent={quickAgent}
      threadId={threadId}
      mode="quick"
      onOpenThread={(id) => {
        setThreadId(id);
        setSearchParams({ thread: id }, { replace: true });
      }}
      onNewThread={() => void handleNewThread()}
      onCreateAndSend={async (text) => {
        const created = await octopThreadsApi.createQuick(agentId);
        navigate(`/m/quick?thread=${created.thread_id}`, {
          replace: true,
          state: { pendingText: text },
        });
      }}
      pendingText={pendingText}
      onPendingConsumed={() =>
        navigate(`${location.pathname}${location.search}`, {
          replace: true,
          state: null,
        })
      }
    />
  );
}
