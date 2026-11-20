import {
  Fragment,
  memo,
  useCallback,
  useMemo,
  useState,
  useRef,
  useEffect,
} from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Dropdown } from "antd";
import type { MenuProps } from "antd";
import {
  ChevronRight,
  FolderPlus,
  GitFork,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Search,
  Share2,
  Trash2,
} from "lucide-react";
import cx from "classnames";
import { type Session } from "../hooks/useSessions";
import { saveSessionShared } from "../utils/shareSession";
import type { OctopAgent } from "../../../context/AgentContext";
import { isAgentChatReady } from "../../../utils/agentError";
import {
  confirmDeleteConversation,
  deleteConversation,
} from "../utils/deleteConversation";
import { isImeComposing } from "../../../utils/ime";
import { ExpertIcon } from "../../Experts/components/iconForName";
import { useHiddenSharedExperts } from "../hooks/useHiddenSharedExperts";
import HiddenExpertsToggle from "./HiddenExpertsToggle";
import SessionChannelIcon from "./SessionChannelIcon";
import SessionShareMark from "./SessionShareMark";
import SessionWorkStatusIcon from "./SessionWorkStatusIcon";
import SharedExpertHint, { ExpertOwnerShareFlag } from "./SharedExpertHint";
import RemoteExpertHint from "./RemoteExpertHint";
import TeamChatBadge from "./TeamChatBadge";
import { isTeamAgent } from "../../../utils/teamAgent";
import { useExpertSessionCatalog } from "../hooks/useExpertSessionCatalog";
import { usePinnedExperts } from "../hooks/usePinnedExperts";
import { useSessionWorkIds } from "../hooks/useSessionWorkIds";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import { formatThreadTitle } from "../utils/threadTitle";
import {
  expertVisibleInNavSearch,
  matchesNavQuery,
} from "../utils/navSessionSearch";
import { sortExpertsByPin } from "../utils/pinnedExpertsPrefs";
import {
  readSessionSortMode,
  sortSessionsForDisplay,
  writeSessionSortMode,
  type SessionSortMode,
} from "../utils/sessionSortPrefs";
import {
  compareSessionsByRecency,
  groupSessionsByRecency,
  type SessionGroupKey,
} from "../utils/sessionGroups";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import {
  isDefaultWorkspacePath,
  normalizeWorkspaceDir,
  useAgentWorkspaces,
  workspaceBasename,
} from "../hooks/useAgentWorkspaces";
import ProjectBaoRow from "../../../components/Bao/ProjectBaoRow";
import {
  initialChatNavScope,
  matchesChatNavScope,
  type ChatNavScope,
} from "../utils/chatNavScope";
import ChatNavScopeTabs, {
  ChatNavCloudEntry,
  ChatNavScopeEmpty,
} from "./ChatNavScopeTabs";
import AgentUnreadBadge from "./AgentUnreadBadge";
import ExpertNameLabel from "./ExpertNameLabel";
import ExpertNavActions, { ExpertPinMark } from "./ExpertNavActions";
import ChatEditExpertDrawer, {
  canEditExpertFromChat,
} from "./ChatEditExpertDrawer";
import {
  resolveSessionWorkStatus,
  type SessionWorkStatus,
} from "../utils/sessionWorkStatus";
import styles from "../index.module.less";
import { openAgentUnread } from "../utils/openUnreadSession";
import { useDebouncedValue } from "../../../hooks/useDebouncedValue";

/** 侧栏一次最多挂到 DOM 的行数，避免几百条时首屏一次性渲染。 */
const LIST_PAGE_SIZE = 40;

/** Sessions without a workspace, and default-home experts, share this project. */
const DEFAULT_PROJECT_KEY = "default";

/** 搜索框自己持有即时输入，父级只接收防抖后的值，输入不被长列表阻塞。 */
function NavSearchInput({
  onQueryChange,
  placeholder,
  ariaLabel,
}: {
  onQueryChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
}) {
  const [value, setValue] = useState("");
  const debounced = useDebouncedValue(value, 180);

  useEffect(() => {
    onQueryChange(debounced);
  }, [debounced, onQueryChange]);

  return (
    <div className={styles.sessionSearchWrap} data-octop-no-drag>
      <Search size={14} className={styles.sessionSearchIcon} strokeWidth={2} />
      <input
        type="search"
        className={styles.sessionSearchInput}
        value={value}
        onChange={(event) => {
          const next = event.target.value;
          setValue(next);
          // 清空立即生效，不等防抖。
          if (!next) onQueryChange("");
        }}
        placeholder={placeholder}
        aria-label={ariaLabel}
      />
    </div>
  );
}

/** 滚到底部附近再追加一页；IntersectionObserver 不可用时保留可点按钮。 */
function RevealMore({
  label,
  onReveal,
}: {
  label: string;
  onReveal: () => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onReveal();
      },
      { rootMargin: "160px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [onReveal]);

  return (
    <button
      ref={ref}
      type="button"
      className={styles.sessionLoadMore}
      onClick={onReveal}
    >
      {label}
    </button>
  );
}

/** 会话目录首屏加载：与真实行同高的骨架，避免列表从空白跳变成内容。 */
function SessionListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className={styles.sessionSkeleton} aria-hidden="true">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className={styles.sessionSkeletonRow}>
          <span className={styles.sessionSkeletonAvatar} />
          <span
            className={styles.sessionSkeletonLine}
            style={{ width: `${82 - index * 11}%` }}
          />
        </div>
      ))}
    </div>
  );
}

interface SessionItemProps {
  session: Session;
  /** Set in the flat "sessions" list: shows which expert owns this thread. */
  agent?: OctopAgent;
  isActive: boolean;
  workStatus?: SessionWorkStatus;
  onSelect: (id: string) => void;
  onDelete: (
    id: string,
    compact: boolean,
  ) => void | Promise<boolean | null | void>;
  onRename: (id: string, name: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onFork: (id: string) => void;
  onContribute: (id: string, contributed: boolean) => void;
  shareable: boolean;
  forkDisabled?: boolean;
  forkDisabledHint?: string;
}

const SessionItem = memo(function SessionItem({
  session,
  agent,
  isActive,
  workStatus = "idle",
  onSelect,
  onDelete,
  onRename,
  onPin,
  onFork,
  onContribute,
  shareable,
  forkDisabled,
  forkDisabledHint,
}: SessionItemProps) {
  const { t } = useTranslation();
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(session.name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isEditing) setEditValue(session.name);
  }, [session.name, isEditing]);

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isEditing]);

  const commitEdit = useCallback(() => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== session.name) {
      onRename(session.id, trimmed);
    } else {
      setEditValue(session.name);
    }
    setIsEditing(false);
  }, [editValue, session.name, session.id, onRename]);

  const itemForkDisabled = Boolean(forkDisabled) || !session.hasActivity;
  const itemForkHint = !session.hasActivity
    ? t("chat.forkNoAssistant")
    : forkDisabledHint;
  const owned = session.owned !== false;
  const quickCreator = owned
    ? t("chat.quickChatMe", "我")
    : session.createdBy || "—";

  const menuItems: MenuProps["items"] = owned
    ? [
        ...(shareable
          ? [
              {
                key: "contribute",
                label: session.contributed
                  ? t("chat.uncontribute", "取消共享")
                  : t("chat.contribute", "共享会话"),
                icon: <Share2 size={14} />,
                onClick: (event: { domEvent: { stopPropagation(): void } }) => {
                  event.domEvent.stopPropagation();
                  onContribute(session.id, !session.contributed);
                },
              },
            ]
          : []),
        {
          key: "pin",
          label: session.pinned
            ? t("chat.unpin", "取消置顶")
            : t("chat.pin", "置顶"),
          icon: session.pinned ? <PinOff size={14} /> : <Pin size={14} />,
          onClick: ({ domEvent }) => {
            domEvent.stopPropagation();
            onPin(session.id, !session.pinned);
          },
        },
        {
          key: "fork",
          label: t("chat.fork", "分叉"),
          icon: <GitFork size={14} />,
          disabled: itemForkDisabled,
          title: itemForkDisabled && itemForkHint ? itemForkHint : undefined,
          onClick: ({ domEvent }) => {
            domEvent.stopPropagation();
            onFork(session.id);
          },
        },
        {
          key: "rename",
          label: t("common.rename"),
          icon: <Pencil size={14} />,
          onClick: ({ domEvent }) => {
            domEvent.stopPropagation();
            setIsEditing(true);
          },
        },
        {
          key: "delete",
          label: t("common.delete", "Delete"),
          icon: <Trash2 size={14} />,
          danger: true,
          onClick: ({ domEvent }) => {
            domEvent.stopPropagation();
            confirmDeleteConversation(t, (compact) =>
              onDelete(session.id, compact),
            );
          },
        },
      ]
    : [];

  return (
    <div
      className={cx(
        styles.sessionRow,
        isActive && styles.sessionRowActive,
        session.pinned && styles.sessionRowPinned,
      )}
      onClick={() => {
        if (!isEditing) onSelect(session.id);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !isEditing) {
          e.preventDefault();
          onSelect(session.id);
        }
      }}
    >
      <span className={styles.sessionRowLead}>
        {workStatus !== "idle" ? (
          <SessionWorkStatusIcon status={workStatus} />
        ) : (
          <SessionChannelIcon
            channelType={session.channelType}
            size={12}
            className={styles.sessionRowIcon}
          />
        )}
      </span>
      {isEditing ? (
        <input
          ref={inputRef}
          className={styles.sessionNameInput}
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={(e) => {
            if (isImeComposing(e)) return;
            if (e.key === "Enter") commitEdit();
            if (e.key === "Escape") {
              setEditValue(session.name);
              setIsEditing(false);
            }
          }}
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <>
          <span className={styles.sessionRowTitleGroup}>
            <span className={styles.sessionRowTitle}>{session.name}</span>
            <SessionShareMark
              contributed={session.contributed}
              owned={session.owned}
            />
            {session.quickChat ? (
              <span
                className={styles.sessionQuickBadge}
                title={t("chat.quickChatMeta", {
                  defaultValue:
                    "快速对话 · {{creator}} · {{expert}} · 不使用工作区",
                  creator: quickCreator,
                  expert: agent?.name || "",
                })}
              >
                {t("chat.quickChat", "快速对话")}
                <span className={styles.sessionQuickBadgeBy}>
                  · {quickCreator}
                </span>
              </span>
            ) : null}
          </span>
          {agent ? (
            <span className={styles.sessionRowAgent} title={agent.name}>
              <ExpertIcon
                iconUrl={agent.icon_url}
                iconName={agent.icon_name}
                size={12}
              />
              <span className={styles.sessionRowAgentName}>{agent.name}</span>
            </span>
          ) : null}
          {session.pinned ? (
            <span
              className={styles.sessionRowPinIndicator}
              title={t("chat.unpin")}
            >
              <Pin size={12} strokeWidth={2} />
            </span>
          ) : null}
          {menuItems && menuItems.length > 0 ? (
            <Dropdown
              menu={{ items: menuItems }}
              trigger={["click"]}
              placement="bottomRight"
            >
              <button
                type="button"
                className={styles.sessionRowMore}
                aria-label={t("common.more", "More")}
                onClick={(e) => e.stopPropagation()}
              >
                <MoreHorizontal size={15} />
              </button>
            </Dropdown>
          ) : null}
        </>
      )}
    </div>
  );
});

interface AgentCardProps {
  agent: OctopAgent;
  sessions: Session[];
  activeId: string | null;
  searchQuery: string;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onFetchAllSessions: () => void;
  onSelect: (sessionId: string, agentId: string) => void;
  onNewChat: (agentId: string, projectId?: string | null) => void;
  onDelete: (
    id: string,
    compact: boolean,
  ) => void | Promise<boolean | null | void>;
  onRename: (id: string, name: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onFork: (id: string, agentId?: string | null) => void;
  onContribute: (id: string, contributed: boolean) => void;
  activeForkDisabled?: boolean;
  activeForkDisabledHint?: string;
  onHide?: () => void;
  onUnhide?: () => void;
  pinned?: boolean;
  onTogglePin?: () => void;
  onEdit?: () => void;
  liveWorkingIds: ReadonlySet<string>;
  sortMode: SessionSortMode;
}

function ActiveAgentCard({
  agent,
  sessions,
  activeId,
  searchQuery,
  hasMore,
  loadingMore,
  onLoadMore,
  onFetchAllSessions,
  onSelect,
  onNewChat,
  onDelete,
  onRename,
  onPin,
  onFork,
  onContribute,
  activeForkDisabled,
  activeForkDisabledHint,
  onHide,
  onUnhide,
  pinned = false,
  onTogglePin,
  onEdit,
  liveWorkingIds,
  sortMode,
}: AgentCardProps) {
  const { t, i18n } = useTranslation();
  const accent = agent.color || "#6366f1";
  const serverTimezone = useServerTimezone();

  const filteredSessions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const base = q
      ? sessions.filter((s) => s.name.toLowerCase().includes(q))
      : sessions;
    return sortSessionsForDisplay(base, sortMode, i18n.language);
  }, [sessions, searchQuery, sortMode, i18n.language]);

  // 单个专家下可能有几百条会话，先挂一页，滚动到底再追加。
  const [visibleSessionCount, setVisibleSessionCount] =
    useState(LIST_PAGE_SIZE);
  useEffect(() => {
    setVisibleSessionCount(LIST_PAGE_SIZE);
  }, [searchQuery, sessions]);
  const visibleSessions = filteredSessions.slice(0, visibleSessionCount);

  // 最近排序时按「置顶/今天/昨天/过去 7 天/过去 30 天/更早」插入分组标题行。
  const showGroupHeaders = sortMode === "recent";
  const sessionRows = useMemo<
    Array<{ key: string; groupKey?: SessionGroupKey; session?: Session }>
  >(() => {
    const rows: Array<{
      key: string;
      groupKey?: SessionGroupKey;
      session?: Session;
    }> = [];
    if (!showGroupHeaders) {
      for (const session of visibleSessions) {
        rows.push({ key: session.id, session });
      }
      return rows;
    }
    for (const group of groupSessionsByRecency(
      visibleSessions,
      serverTimezone,
    )) {
      rows.push({ key: `group-${group.key}`, groupKey: group.key });
      for (const session of group.sessions) {
        rows.push({ key: session.id, session });
      }
    }
    return rows;
  }, [showGroupHeaders, visibleSessions, serverTimezone]);
  const revealMoreSessions = useCallback(() => {
    setVisibleSessionCount((count) => count + LIST_PAGE_SIZE);
  }, []);

  const fetchAllRequestedRef = useRef(false);
  useEffect(() => {
    const searching = Boolean(searchQuery.trim());
    if (!searching) {
      fetchAllRequestedRef.current = false;
      return;
    }
    if (fetchAllRequestedRef.current) return;
    fetchAllRequestedRef.current = true;
    onFetchAllSessions();
  }, [searchQuery, onFetchAllSessions]);

  const showExpandMore = hasMore && !searchQuery.trim();
  const sessionsEnabled = isAgentChatReady(agent.state);

  return (
    <div
      className={styles.agentCardActive}
      style={{
        background: `${accent}08`,
        borderColor: `${accent}18`,
      }}
    >
      <div className={styles.agentCardProfile}>
        <SharedExpertHint agent={agent}>
          <div
            className={styles.agentCardAvatar}
            style={{
              color: accent,
              background: `${accent}14`,
              boxShadow: `0 0 0 1px ${accent}22`,
            }}
          >
            <ExpertIcon
              iconUrl={agent.icon_url}
              iconName={agent.icon_name}
              size={agent.icon_url?.trim() ? 28 : 16}
            />
          </div>
        </SharedExpertHint>
        <div className={styles.agentCardInfo}>
          <div className={styles.agentCardNameRow}>
            <div className={styles.agentNameCluster}>
              <ExpertNameLabel
                name={agent.name}
                className={styles.agentCardName}
              />
              <ExpertOwnerShareFlag agent={agent} />
              <ExpertPinMark pinned={pinned} />
              <TeamChatBadge agent={agent} compact />
              <RemoteExpertHint agent={agent} compact />
            </div>
            <AgentUnreadBadge
              count={agent.unread_count ?? 0}
              onOpen={() => {
                void openAgentUnread(agent.agent_id, sessions, onSelect);
              }}
            />
            {onTogglePin ? (
              <ExpertNavActions
                variant="classic"
                pinned={pinned}
                onTogglePin={onTogglePin}
                onNewChat={() => onNewChat(agent.agent_id)}
                onHide={onHide}
                onUnhide={onUnhide}
                onEdit={onEdit}
                editingTeam={isTeamAgent(agent)}
              />
            ) : null}
          </div>
          {agent.description ? (
            <div className={styles.agentCardDesc}>{agent.description}</div>
          ) : (
            <div className={styles.agentCardDescMuted}>
              {t("chat.agentNoDescription", "暂无描述")}
            </div>
          )}
        </div>
      </div>

      <div className={styles.agentCardSessions}>
        {!sessionsEnabled ? (
          <div className={styles.agentCardSessionsEmpty}>
            {t("chat.agentNotRunningHint")}
          </div>
        ) : sessions.length === 0 ? (
          <div className={styles.agentCardSessionsEmpty}>
            <span>{t("chat.noSessionsYet", "直接发消息即可开始对话")}</span>
            <button
              type="button"
              className={styles.agentCardSessionsEmptyAction}
              onClick={() => onNewChat(agent.agent_id)}
            >
              {t("chat.palette.newChat", "新建会话")}
            </button>
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className={styles.agentCardSessionsEmpty}>
            {t("chat.noSearchResults", "没有匹配的会话")}
          </div>
        ) : (
          <>
            {sessionRows.map((row) => {
              if (row.groupKey && !row.session) {
                const [labelKey, fallback] = GROUP_LABELS[row.groupKey];
                return (
                  <div
                    key={row.key}
                    className={styles.sessionGroupLabel}
                    aria-hidden="true"
                  >
                    {t(labelKey, fallback)}
                  </div>
                );
              }
              if (!row.session) return null;
              const s = row.session;
              return (
                <SessionItem
                  key={s.id}
                  session={s}
                  isActive={activeId === s.id}
                  workStatus={resolveSessionWorkStatus(s, liveWorkingIds)}
                  onSelect={(id) => onSelect(id, agent.agent_id)}
                  onDelete={onDelete}
                  onRename={onRename}
                  onPin={onPin}
                  onContribute={onContribute}
                  shareable={Boolean(agent.is_shared)}
                  onFork={(id) => onFork(id, agent.agent_id)}
                  forkDisabled={
                    activeId === s.id ? activeForkDisabled : undefined
                  }
                  forkDisabledHint={
                    activeId === s.id ? activeForkDisabledHint : undefined
                  }
                />
              );
            })}
            {filteredSessions.length > visibleSessions.length ? (
              <RevealMore
                label={t("chat.expandMore", "展开更多")}
                onReveal={revealMoreSessions}
              />
            ) : showExpandMore ? (
              <button
                type="button"
                className={styles.sessionLoadMore}
                onClick={onLoadMore}
                disabled={loadingMore}
              >
                {loadingMore
                  ? t("common.loading")
                  : t("chat.expandMore", "展开更多")}
              </button>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

interface AgentRowProps {
  agent: OctopAgent;
  onSelect: () => void;
  onNewChat?: () => void;
  onHide?: () => void;
  onUnhide?: () => void;
  pinned?: boolean;
  onTogglePin?: () => void;
  onEdit?: () => void;
  onOpenUnread: () => void;
}

function InactiveAgentRow({
  agent,
  onSelect,
  onNewChat,
  onHide,
  onUnhide,
  pinned = false,
  onTogglePin,
  onEdit,
  onOpenUnread,
}: AgentRowProps) {
  const accent = agent.color || "#6366f1";

  return (
    <div
      className={styles.agentRow}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <SharedExpertHint agent={agent}>
        <div
          className={styles.agentRowAvatar}
          style={{ color: accent, background: `${accent}12` }}
        >
          <ExpertIcon
            iconUrl={agent.icon_url}
            iconName={agent.icon_name}
            size={agent.icon_url?.trim() ? 26 : 14}
          />
        </div>
      </SharedExpertHint>
      <div className={styles.agentRowInfo}>
        <div className={styles.agentRowNameRow}>
          <div className={styles.agentNameCluster}>
            <ExpertNameLabel
              name={agent.name}
              className={styles.agentRowName}
            />
            <ExpertOwnerShareFlag agent={agent} />
            <ExpertPinMark pinned={pinned} />
            <TeamChatBadge agent={agent} compact />
            <RemoteExpertHint agent={agent} compact />
          </div>
          <AgentUnreadBadge
            count={agent.unread_count ?? 0}
            onOpen={onOpenUnread}
          />
          {onNewChat && onTogglePin ? (
            <ExpertNavActions
              variant="classic"
              pinned={pinned}
              onTogglePin={onTogglePin}
              onNewChat={onNewChat}
              onHide={onHide}
              onUnhide={onUnhide}
              onEdit={onEdit}
              editingTeam={isTeamAgent(agent)}
            />
          ) : null}
        </div>
        <div className={styles.agentRowDesc}>{agent.description || "—"}</div>
      </div>
    </div>
  );
}

/** 会话时间分组标题文案（键, 兜底文案）。 */
const GROUP_LABELS: Record<SessionGroupKey, [string, string]> = {
  pinned: ["chat.sessionGroup.pinned", "置顶"],
  today: ["chat.sessionGroup.today", "今天"],
  yesterday: ["chat.sessionGroup.yesterday", "昨天"],
  week: ["chat.sessionGroup.week", "过去 7 天"],
  month: ["chat.sessionGroup.month", "过去 30 天"],
  older: ["chat.sessionGroup.older", "更早"],
};

interface SessionListProps {
  agents: OctopAgent[];
  /**
   * Experts the user owns that are not chat-ready (stopped, failed, still
   * starting). The rail lists only agents that can chat, so without this count
   * "no agents here" cannot tell "you have none" from "none are running".
   */
  unreadyExperts?: number;
  sessions: Session[];
  activeId: string | null;
  activeAgentId: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onFetchAllSessions: () => void;
  onSelect: (sessionId: string, agentId: string) => void;
  onAgentSelect: (agentId: string) => void;
  onNewChat: (agentId: string, projectId?: string | null) => void;
  /** Open the folder picker that creates a workspace-backed project. */
  onNewProject?: () => void;
  onDelete: (
    id: string,
    compact: boolean,
  ) => void | Promise<boolean | null | void>;
  onRename: (id: string, name: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onFork: (id: string, agentId?: string | null) => void;
  activeForkDisabled?: boolean;
  activeForkDisabledHint?: string;
}

export default function SessionList({
  agents,
  unreadyExperts = 0,
  sessions,
  activeId,
  activeAgentId,
  hasMore,
  loadingMore,
  onLoadMore,
  onFetchAllSessions,
  onSelect,
  onAgentSelect,
  onNewChat,
  onNewProject,
  onDelete,
  onRename,
  onPin,
  onFork,
  activeForkDisabled,
  activeForkDisabledHint,
}: SessionListProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const liveWorkingIds = useSessionWorkIds();
  const [searchQuery, setSearchQuery] = useState("");
  const [sortMode, setSortMode] =
    useState<SessionSortMode>(readSessionSortMode);
  const changeSortMode = useCallback((mode: SessionSortMode) => {
    setSortMode(mode);
    writeSessionSortMode(mode);
  }, []);
  const [showingHidden, setShowingHidden] = useState(false);
  const [editAgent, setEditAgent] = useState<OctopAgent | null>(null);
  const [navScope, setNavScope] = useState<ChatNavScope>(initialChatNavScope);
  const { filterVisible, pickHidden, hide, unhide, canHide } =
    useHiddenSharedExperts();
  const { pinnedIds, isPinned, togglePin } = usePinnedExperts();

  const hiddenAgents = useMemo(
    () =>
      sortExpertsByPin(pickHidden(agents), pinnedIds).filter((agent) =>
        matchesChatNavScope(agent, navScope),
      ),
    [agents, pickHidden, pinnedIds, navScope],
  );

  const sortedAgents = useMemo(() => {
    const visible = filterVisible(agents);
    return sortExpertsByPin(visible, pinnedIds).filter((agent) =>
      matchesChatNavScope(agent, navScope),
    );
  }, [agents, filterVisible, pinnedIds, navScope]);

  const expandedAgentId = useMemo(() => {
    const activeInScope = sortedAgents.some(
      (agent) => agent.agent_id === activeAgentId,
    );
    if (activeInScope) return activeAgentId;
    // Browsing another tab keeps the open chat; don't expand a stranger.
    if (activeAgentId) return null;
    return sortedAgents[0]?.agent_id ?? null;
  }, [activeAgentId, sortedAgents]);
  const searching = searchQuery.trim().length > 0;
  // "projects" groups by the workspace each expert already runs in, so
  // workspaces are only resolved while that tab is open.
  const workspaces = useAgentWorkspaces(agents, navScope === "projects");
  // 时间分组标题按服务端时区切日界；跨专家平铺与专家内列表保持一致。
  const serverTimezone = useServerTimezone();
  const fetchAllRequestedRef = useRef(false);
  useEffect(() => {
    if (!searching) {
      fetchAllRequestedRef.current = false;
      return;
    }
    if (fetchAllRequestedRef.current) return;
    fetchAllRequestedRef.current = true;
    onFetchAllSessions();
  }, [onFetchAllSessions, searching]);
  // The flat "sessions" and "projects" tabs need every expert's threads even
  // without a query.
  const catalog = useExpertSessionCatalog(
    sortedAgents,
    searching || navScope === "sessions" || navScope === "projects",
  );
  const sessionsFor = useCallback(
    (agentId: string): Session[] => {
      const catalogList = catalog.byAgent[agentId] ?? [];
      if (agentId === activeAgentId && sessions.length >= catalogList.length) {
        return sessions;
      }
      return catalogList.length > 0
        ? catalogList
        : agentId === activeAgentId
        ? sessions
        : [];
    },
    [activeAgentId, catalog.byAgent, sessions],
  );
  const listedAgents = useMemo(() => {
    if (!searching) return sortedAgents;
    return sortedAgents.filter((agent) =>
      expertVisibleInNavSearch(
        agent.name,
        sessionsFor(agent.agent_id).map((session) => session.name),
        searchQuery,
      ),
    );
  }, [searchQuery, searching, sessionsFor, sortedAgents]);

  /**
   * "sessions" tab: every expert's threads in one recency-ordered list, so a
   * conversation is reachable without first entering an expert's private view.
   * Empty threads are kept (they are resumable), but they sort last.
   */
  const flatEntries = useMemo(() => {
    if (navScope !== "sessions") return [];
    const q = searchQuery.trim().toLowerCase();
    const rows: Array<{ session: Session; agent: OctopAgent }> = [];
    for (const agent of listedAgents) {
      const agentMatches = q.length > 0 && agent.name.toLowerCase().includes(q);
      for (const session of sessionsFor(agent.agent_id)) {
        if (q && !agentMatches && !session.name.toLowerCase().includes(q)) {
          continue;
        }
        rows.push({ session, agent });
      }
    }
    rows.sort((a, b) => {
      if (sortMode === "name") {
        return a.session.name.localeCompare(b.session.name, i18n.language);
      }
      return compareSessionsByRecency(a.session, b.session);
    });
    return rows;
  }, [i18n.language, listedAgents, navScope, searchQuery, sessionsFor, sortMode]);

  /**
   * "projects" tab: one project per ``workspace_dir``. Experts bound to the same
   * folder share a project. Experts with no binding — including the auto-created
   * agent home — all land in the default workspace project, so no conversation
   * drops out of the list.
   */
  const projectGroups = useMemo(() => {
    if (navScope !== "projects") return [];
    const q = searchQuery.trim().toLowerCase();
    const groups = new Map<
      string,
      {
        key: string;
        title: string;
        dir: string | null;
        isDefault: boolean;
        /** Expert that owns the project folder; used for "new chat" here. */
        agentId: string;
        /** ``projects`` table id; null for legacy workspace_dir groups. */
        projectId: string | null;
        entries: Array<{ session: Session; agent: OctopAgent }>;
      }
    >();
    for (const agent of listedAgents) {
      const dir = workspaces.byAgent[agent.agent_id]?.workspaceDir ?? null;
      const attributed =
        Boolean(dir) && !isDefaultWorkspacePath(dir, workspaces.agentsRoot);
      const agentMatches = q.length > 0 && agent.name.toLowerCase().includes(q);
      let assigned = 0;
      for (const session of sessionsFor(agent.agent_id)) {
        if (q && !agentMatches && !session.name.toLowerCase().includes(q)) {
          continue;
        }
        assigned += 1;
        // Migrated conversations group by the projects table; un-migrated ones
        // keep the legacy workspace_dir grouping until the upgrade runs.
        const projectId = session.projectId ?? null;
        const sessionKey = projectId
          ? `prj:${projectId}`
          : attributed && dir
            ? `ws:${normalizeWorkspaceDir(dir)}`
            : DEFAULT_PROJECT_KEY;
        let group = groups.get(sessionKey);
        if (!group) {
          group = {
            key: sessionKey,
            title: projectId
              ? session.projectName || t("chat.workspaceDefaultName", "默认工作区")
              : attributed && dir
                ? workspaceBasename(dir)
                : t("chat.workspaceDefaultName", "默认工作区"),
            dir: projectId
              ? session.workspaceDir ?? dir
              : attributed
                ? dir
                : null,
            isDefault: !projectId && !attributed,
            agentId: agent.agent_id,
            projectId,
            entries: [],
          };
          groups.set(sessionKey, group);
        } else if (agent.agent_id === activeAgentId) {
          group.agentId = agent.agent_id;
        }
        group.entries.push({ session, agent });
      }
      // Experts without conversations still show their workspace in this tab.
      if (assigned === 0 && !q) {
        const key = attributed && dir
          ? `ws:${normalizeWorkspaceDir(dir)}`
          : DEFAULT_PROJECT_KEY;
        if (!groups.has(key)) {
          groups.set(key, {
            key,
            title:
              attributed && dir
                ? workspaceBasename(dir)
                : t("chat.workspaceDefaultName", "默认工作区"),
            dir: attributed ? dir : null,
            isDefault: !attributed,
            agentId: agent.agent_id,
            projectId: null,
            entries: [],
          });
        }
      }
    }
    const rows = [...groups.values()];
    for (const group of rows) {
      group.entries.sort((a, b) =>
        sortMode === "name"
          ? a.session.name.localeCompare(b.session.name, i18n.language)
          : compareSessionsByRecency(a.session, b.session),
      );
    }
    rows.sort((a, b) => {
      if (a.isDefault !== b.isDefault) return a.isDefault ? 1 : -1;
      const ta = a.entries[0]?.session.updatedAt;
      const tb = b.entries[0]?.session.updatedAt;
      if (ta || tb) {
        return (tb ? Date.parse(tb) : 0) - (ta ? Date.parse(ta) : 0);
      }
      return a.title.localeCompare(b.title, i18n.language);
    });
    return rows;
  }, [
    activeAgentId,
    i18n.language,
    listedAgents,
    navScope,
    searchQuery,
    sessionsFor,
    sortMode,
    t,
    workspaces.agentsRoot,
    workspaces.byAgent,
  ]);

  /** Wait for every listed expert's workspace before grouping. */
  const workspacesReady = useMemo(
    () =>
      workspaces.rootReady &&
      listedAgents.every((agent) => workspaces.byAgent[agent.agent_id]),
    [listedAgents, workspaces.byAgent, workspaces.rootReady],
  );

  /** Project holding the open conversation; expanded by default. */
  const currentProjectKey = useMemo(() => {
    if (!activeAgentId) return null;
    const dir = workspaces.byAgent[activeAgentId]?.workspaceDir ?? null;
    if (!dir || isDefaultWorkspacePath(dir, workspaces.agentsRoot)) {
      return DEFAULT_PROJECT_KEY;
    }
    return `ws:${normalizeWorkspaceDir(dir)}`;
  }, [activeAgentId, workspaces.agentsRoot, workspaces.byAgent]);

  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(
    () => new Set(),
  );
  useEffect(() => {
    if (!currentProjectKey) return;
    setExpandedProjects((prev) =>
      prev.has(currentProjectKey)
        ? prev
        : new Set(prev).add(currentProjectKey),
    );
  }, [currentProjectKey]);
  const toggleProject = useCallback((key: string) => {
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // 每个项目各自挂一页会话，展开更多只影响该项目。
  const [projectLimits, setProjectLimits] = useState<Record<string, number>>({});
  const revealMoreProjectSessions = useCallback((key: string) => {
    setProjectLimits((prev) => ({
      ...prev,
      [key]: (prev[key] ?? LIST_PAGE_SIZE) + LIST_PAGE_SIZE,
    }));
  }, []);

  const [visibleFlatCount, setVisibleFlatCount] = useState(LIST_PAGE_SIZE);
  useEffect(() => {
    setVisibleFlatCount(LIST_PAGE_SIZE);
  }, [navScope, searchQuery]);
  const visibleFlat = flatEntries.slice(0, visibleFlatCount);

  // 「最近」排序下，跨专家平铺也要有「置顶/今天/昨天/…」分组标题，
  // 与专家内列表共用同一套分组规则，避免会话优先侧栏丢掉时间分组。
  const flatGroups = useMemo(() => {
    if (navScope !== "sessions" || sortMode !== "recent") return null;
    const entryBySession = new Map(
      visibleFlat.map((entry) => [entry.session.id, entry]),
    );
    return groupSessionsByRecency(
      visibleFlat.map((entry) => entry.session),
      serverTimezone,
    ).map((group) => ({
      key: group.key,
      entries: group.sessions
        .map((session) => entryBySession.get(session.id))
        .filter(
          (
            entry,
          ): entry is { session: Session; agent: OctopAgent } =>
            entry !== undefined,
        ),
    }));
  }, [navScope, serverTimezone, sortMode, visibleFlat]);

  // 专家数量多时同样先挂一页，滚动到底再追加。
  const [visibleAgentCount, setVisibleAgentCount] = useState(LIST_PAGE_SIZE);
  useEffect(() => {
    setVisibleAgentCount(LIST_PAGE_SIZE);
  }, [searchQuery]);
  const visibleAgents = listedAgents.slice(0, visibleAgentCount);
  const revealMoreAgents = useCallback(() => {
    setVisibleAgentCount((count) => count + LIST_PAGE_SIZE);
  }, []);
  const listedHiddenAgents = useMemo(() => {
    if (!showingHidden) return [];
    const shown = new Set(listedAgents.map((agent) => agent.agent_id));
    return hiddenAgents.filter((agent) => {
      if (shown.has(agent.agent_id)) return false;
      if (!searching) return true;
      return matchesNavQuery(agent.name, searchQuery);
    });
  }, [hiddenAgents, listedAgents, searchQuery, searching, showingHidden]);

  const deleteOther = useCallback(
    async (agentId: string, id: string, compact: boolean) => {
      const deleted = await deleteConversation(agentId, id, compact, t);
      if (deleted !== true) return deleted;
      catalog.patch(agentId, (prev) =>
        prev.filter((session) => session.id !== id),
      );
      return true;
    },
    [catalog, t],
  );
  const renameOther = useCallback(
    (agentId: string, id: string, name: string) => {
      const next = formatThreadTitle(name) || name.trim();
      if (!next) return;
      void octopThreadsApi.rename(agentId, id, next).catch(() => {});
      catalog.patch(agentId, (prev) =>
        prev.map((session) =>
          session.id === id ? { ...session, name: next } : session,
        ),
      );
    },
    [catalog],
  );
  const pinOther = useCallback(
    (agentId: string, id: string, pinned: boolean) => {
      void octopThreadsApi.patch(agentId, id, { pinned }).catch(() => {});
      catalog.patch(agentId, (prev) =>
        prev.map((session) =>
          session.id === id ? { ...session, pinned } : session,
        ),
      );
    },
    [catalog],
  );
  const contributeSession = useCallback(
    (agentId: string, id: string, contributed: boolean) => {
      void saveSessionShared(
        agentId,
        id,
        contributed,
        () => {
          catalog.patch(agentId, (prev) =>
            prev.map((session) =>
              session.id === id ? { ...session, contributed } : session,
            ),
          );
        },
        t("chat.shareFailed", "没能改共享状态，请再试一次"),
      );
    },
    [catalog, t],
  );

  /**
   * The rail only lists experts that can chat right now, so "no agents here"
   * has two very different causes: the user has none, or the ones they have
   * are stopped / waiting on a model. Only the first one should be answered
   * with "create your first expert".
   */
  const emptyAgentsCopy =
    unreadyExperts > 0
      ? { text: t("chat.noChattableAgentsHint"), action: t("chat.goToExperts") }
      : { text: t("chat.noAgentsHint"), action: t("chat.createExpert") };

  // Cloud collaboration entry badge: how many remote experts / teams exist.
  const cloudAgentCount = useMemo(
    () => agents.filter((agent) => matchesChatNavScope(agent, "cloud")).length,
    [agents],
  );

  /** Flat rows (sessions / projects) share this wiring. */
  const renderSessionRow = (session: Session, agent: OctopAgent) => {
    const isActiveAgent = agent.agent_id === activeAgentId;
    return (
      <SessionItem
        key={`${agent.agent_id}:${session.id}`}
        session={session}
        agent={agent}
        isActive={activeId === session.id}
        workStatus={resolveSessionWorkStatus(session, liveWorkingIds)}
        onSelect={(id) => onSelect(id, agent.agent_id)}
        onDelete={
          isActiveAgent
            ? onDelete
            : (id, compact) => deleteOther(agent.agent_id, id, compact)
        }
        onRename={
          isActiveAgent
            ? onRename
            : (id, name) => renameOther(agent.agent_id, id, name)
        }
        onPin={
          isActiveAgent
            ? onPin
            : (id, pinned) => pinOther(agent.agent_id, id, pinned)
        }
        onContribute={(id, contributed) =>
          contributeSession(agent.agent_id, id, contributed)
        }
        shareable={Boolean(agent.is_shared)}
        onFork={(id) => onFork(id, agent.agent_id)}
        forkDisabled={activeId === session.id ? activeForkDisabled : undefined}
        forkDisabledHint={
          activeId === session.id ? activeForkDisabledHint : undefined
        }
      />
    );
  };

  const renderAgentRow = (agent: OctopAgent, hiddenRow: boolean) => {
    const isActive = agent.agent_id === activeAgentId;
    const hits = searching
      ? sessionsFor(agent.agent_id).filter((session) =>
          matchesNavQuery(session.name, searchQuery),
        )
      : [];
    const expanded = hiddenRow
      ? isActive
      : searching
      ? hits.length > 0
      : agent.agent_id === expandedAgentId;
    if (expanded) {
      return (
        <ActiveAgentCard
          key={agent.agent_id}
          agent={agent}
          sessions={isActive ? sessions : hits}
          activeId={activeId}
          searchQuery={isActive ? searchQuery : ""}
          hasMore={isActive ? hasMore : false}
          loadingMore={isActive ? loadingMore : false}
          onLoadMore={isActive ? onLoadMore : () => undefined}
          onFetchAllSessions={isActive ? onFetchAllSessions : () => undefined}
          onSelect={onSelect}
          onNewChat={onNewChat}
          onDelete={
            isActive
              ? onDelete
              : (id, compact) => deleteOther(agent.agent_id, id, compact)
          }
          onRename={
            isActive
              ? onRename
              : (id, name) => renameOther(agent.agent_id, id, name)
          }
          onPin={
            isActive
              ? onPin
              : (id, pinned) => pinOther(agent.agent_id, id, pinned)
          }
          onContribute={(id, contributed) =>
            contributeSession(agent.agent_id, id, contributed)
          }
          onFork={onFork}
          activeForkDisabled={activeForkDisabled}
          activeForkDisabledHint={activeForkDisabledHint}
          onHide={
            !hiddenRow && canHide(agent)
              ? () => hide(agent.agent_id)
              : undefined
          }
          onUnhide={hiddenRow ? () => unhide(agent.agent_id) : undefined}
          pinned={isPinned(agent.agent_id)}
          onTogglePin={() => togglePin(agent.agent_id)}
          onEdit={
            canEditExpertFromChat(agent) ? () => setEditAgent(agent) : undefined
          }
          liveWorkingIds={liveWorkingIds}
          sortMode={sortMode}
        />
      );
    }
    return (
      <InactiveAgentRow
        key={agent.agent_id}
        agent={agent}
        onSelect={() => onAgentSelect(agent.agent_id)}
        onNewChat={() => onNewChat(agent.agent_id)}
        onHide={
          !hiddenRow && canHide(agent) ? () => hide(agent.agent_id) : undefined
        }
        onUnhide={hiddenRow ? () => unhide(agent.agent_id) : undefined}
        pinned={isPinned(agent.agent_id)}
        onTogglePin={() => togglePin(agent.agent_id)}
        onEdit={
          canEditExpertFromChat(agent) ? () => setEditAgent(agent) : undefined
        }
        onOpenUnread={() => {
          void openAgentUnread(
            agent.agent_id,
            sessionsFor(agent.agent_id),
            onSelect,
          );
        }}
      />
    );
  };

  return (
    <div className={styles.sessionList}>
      <ChatEditExpertDrawer
        agent={editAgent}
        onClose={() => setEditAgent(null)}
      />
      {agents.length > 0 ? (
        <div className={styles.sessionHeaderRow}>
          <NavSearchInput
            onQueryChange={setSearchQuery}
            placeholder={t("chat.searchSessions", "搜索会话")}
            ariaLabel={t("chat.searchSessions", "搜索会话")}
          />
          <div
            className={styles.sessionSortSwitch}
            role="group"
            aria-label={t("chat.sortLabel", "会话排序")}
          >
            <button
              type="button"
              className={cx(
                styles.sessionSortOption,
                sortMode === "recent" && styles.sessionSortOptionActive,
              )}
              aria-pressed={sortMode === "recent"}
              onClick={() => changeSortMode("recent")}
            >
              {t("chat.sortRecent", "最近")}
            </button>
            <button
              type="button"
              className={cx(
                styles.sessionSortOption,
                sortMode === "name" && styles.sessionSortOptionActive,
              )}
              aria-pressed={sortMode === "name"}
              onClick={() => changeSortMode("name")}
            >
              {t("chat.sortName", "名称")}
            </button>
          </div>
        </div>
      ) : null}

      {agents.length > 0 ? (
        <>
          <ChatNavScopeTabs value={navScope} onChange={setNavScope} />
          <ChatNavCloudEntry
            active={navScope === "cloud"}
            count={cloudAgentCount}
            onOpen={() => setNavScope("cloud")}
            onClose={() => setNavScope("sessions")}
          />
        </>
      ) : null}

      {agents.length === 0 ? (
        <div className={styles.sessionEmptyAgents}>
          <p className={styles.sessionEmptyAgentsText}>
            {emptyAgentsCopy.text}
          </p>
          <button
            type="button"
            className={styles.sessionEmptyAgentsLink}
            onClick={() => navigate("/experts")}
          >
            {emptyAgentsCopy.action}
          </button>
        </div>
      ) : navScope === "sessions" ? (
        <div className={styles.sessionItems}>
          {catalog.loading && flatEntries.length === 0 ? (
            <SessionListSkeleton />
          ) : flatEntries.length === 0 ? (
            <div className={styles.sessionEmptyAgents}>
              <p className={styles.sessionEmptyAgentsText}>
                {searching
                  ? t("chat.noSearchResults", "没有匹配的会话")
                  : t("chat.noSessionsYet", "直接发消息即可开始对话")}
              </p>
              {searching ? null : (
                <button
                  type="button"
                  className={styles.sessionEmptyAgentsLink}
                  onClick={() => {
                    const target = activeAgentId ?? agents[0]?.agent_id;
                    if (target) onNewChat(target);
                  }}
                >
                  {t("chat.palette.newChat", "新建会话")}
                </button>
              )}
            </div>
          ) : (
            <>
              {flatGroups
                ? flatGroups.map((group) => {
                    const [labelKey, fallback] = GROUP_LABELS[group.key];
                    return (
                      <Fragment key={`group-${group.key}`}>
                        <div
                          className={styles.sessionGroupLabel}
                          aria-hidden="true"
                        >
                          {t(labelKey, fallback)}
                        </div>
                        {group.entries.map(({ session, agent }) =>
                          renderSessionRow(session, agent),
                        )}
                      </Fragment>
                    );
                  })
                : visibleFlat.map(({ session, agent }) =>
                    renderSessionRow(session, agent),
                  )}
              {flatEntries.length > visibleFlat.length ? (
                <RevealMore
                  label={t("chat.expandMore", "展开更多")}
                  onReveal={() =>
                    setVisibleFlatCount((count) => count + LIST_PAGE_SIZE)
                  }
                />
              ) : null}
            </>
          )}
        </div>
      ) : navScope === "projects" ? (
        <div className={styles.sessionItems}>
          <div className={styles.sessionProjectToolbar}>
            <span className={styles.sessionProjectToolbarLabel}>
              {t("chat.navScopeProjects", "项目")}
            </span>
            {onNewProject ? (
              <button
                type="button"
                className={styles.sessionProjectCreate}
                data-testid="chat-project-create"
                onClick={onNewProject}
              >
                <FolderPlus size={12} />
                {t("chat.projectCreate", "新建项目")}
              </button>
            ) : null}
          </div>
          {!workspacesReady || catalog.loading ? (
            <SessionListSkeleton />
          ) : projectGroups.length === 0 ? (
            <div className={styles.sessionEmptyAgents}>
              <p className={styles.sessionEmptyAgentsText}>
                {t("chat.noSearchResults", "没有匹配的会话")}
              </p>
            </div>
          ) : (
            projectGroups.map((group) => {
              const open = expandedProjects.has(group.key);
              const limit = projectLimits[group.key] ?? LIST_PAGE_SIZE;
              const shown = group.entries.slice(0, limit);
              return (
                <div
                  key={group.key}
                  data-testid="chat-project-group"
                  data-project-key={group.key}
                  data-project-title={group.title}
                  data-expanded={open ? "true" : "false"}
                >
                  <button
                    type="button"
                    className={styles.sessionProjectHeader}
                    data-testid="chat-project-header"
                    aria-expanded={open}
                    onClick={() => {
                      // 空项目没有可打开的会话：直接在该项目里开一个新会话，
                      // 下一次发送由 useChatSend 在项目专家下建线程，而不是留在旧会话。
                      if (
                        group.entries.length === 0 &&
                        group.agentId !== activeAgentId
                      ) {
                        setExpandedProjects((prev) =>
                          prev.has(group.key)
                            ? prev
                            : new Set(prev).add(group.key),
                        );
                        onNewChat(group.agentId, group.projectId);
                        return;
                      }
                      toggleProject(group.key);
                    }}
                  >
                    <ChevronRight
                      size={12}
                      className={cx(
                        styles.sessionProjectChevron,
                        open && styles.sessionProjectChevronOpen,
                      )}
                    />
                    <span
                      className={styles.sessionProjectTitle}
                      title={group.dir ?? undefined}
                    >
                      {group.title}
                    </span>
                    <span
                      className={styles.sessionProjectCount}
                      data-testid="chat-project-count"
                    >
                      {group.entries.length}
                    </span>
                  </button>
                  {open ? (
                    <>
                      <ProjectBaoRow
                        projectKey={group.key}
                        projectName={group.title}
                      />
                      {group.entries.length === 0 ? (
                        <div
                          className={styles.sessionProjectEmpty}
                          data-testid="chat-project-empty"
                        >
                          <span>
                            {t("chat.projectEmptyHint", "这个项目下还没有会话")}
                          </span>
                          <button
                            type="button"
                            className={styles.sessionEmptyAgentsLink}
                            onClick={() => onNewChat(group.agentId, group.projectId)}
                          >
                            {t("chat.palette.newChat", "新建会话")}
                          </button>
                        </div>
                      ) : (
                        <>
                          {shown.map(({ session, agent }) =>
                            renderSessionRow(session, agent),
                          )}
                          {group.entries.length > shown.length ? (
                            <RevealMore
                              label={t("chat.expandMore", "展开更多")}
                              onReveal={() =>
                                revealMoreProjectSessions(group.key)
                              }
                            />
                          ) : null}
                        </>
                      )}
                    </>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      ) : (
        <div className={styles.sessionItems}>
          {listedAgents.length === 0 &&
          (searching || catalog.loading || hiddenAgents.length === 0) ? (
            searching || catalog.loading ? (
              catalog.loading ? (
                <SessionListSkeleton />
              ) : (
                <div className={styles.agentCardSessionsEmpty}>
                  {t("chat.noSearchResults", "没有匹配的会话")}
                </div>
              )
            ) : (
              <ChatNavScopeEmpty scope={navScope} />
            )
          ) : (
            <>
              {visibleAgents.map((agent) => renderAgentRow(agent, false))}
              {listedAgents.length > visibleAgents.length ? (
                <RevealMore
                  label={t("chat.expandMore", "展开更多")}
                  onReveal={revealMoreAgents}
                />
              ) : null}
            </>
          )}
          {hiddenAgents.length > 0 ? (
            <>
              <HiddenExpertsToggle
                expanded={showingHidden}
                count={hiddenAgents.length}
                onToggle={() => setShowingHidden((open) => !open)}
              />
              {listedHiddenAgents.map((agent) => renderAgentRow(agent, true))}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
