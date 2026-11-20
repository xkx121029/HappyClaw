import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import type { OctopAgent } from "../../../context/AgentContext";
import { ExpertIcon } from "../../Experts/components/iconForName";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import {
  confirmDeleteConversation,
  deleteConversation,
} from "../utils/deleteConversation";
import { isAgentChatReady } from "../../../utils/agentError";
import { isImeComposing } from "../../../utils/ime";
import { sortSessions, toSession, type Session } from "../hooks/useSessions";
import { openAgentUnread } from "../utils/openUnreadSession";
import { saveSessionShared } from "../utils/shareSession";
import { formatThreadTitle } from "../utils/threadTitle";
import { onSessionEvent } from "../hooks/chatStore";
import { useExpertSessionCatalog } from "../hooks/useExpertSessionCatalog";
import { useHiddenSharedExperts } from "../hooks/useHiddenSharedExperts";
import HiddenExpertsToggle from "./HiddenExpertsToggle";
import { usePinnedExperts } from "../hooks/usePinnedExperts";
import { useSessionWorkIds } from "../hooks/useSessionWorkIds";
import { sortExpertsByPin } from "../utils/pinnedExpertsPrefs";
import { compareSessionsByRecency } from "../utils/sessionGroups";
import {
  isDefaultWorkspacePath,
  normalizeWorkspaceDir,
  useAgentWorkspaces,
  workspaceBasename,
} from "../hooks/useAgentWorkspaces";
import {
  initialChatNavScope,
  matchesChatNavScope,
  type ChatNavScope,
} from "../utils/chatNavScope";
import AgentUnreadBadge from "./AgentUnreadBadge";
import ChatNavScopeTabs, {
  ChatNavCloudEntry,
  ChatNavScopeEmpty,
} from "./ChatNavScopeTabs";
import {
  expertVisibleInNavSearch,
  matchesNavQuery,
} from "../utils/navSessionSearch";
import {
  resolveSessionWorkStatus,
  type SessionWorkStatus,
} from "../utils/sessionWorkStatus";
import SharedExpertHint, { ExpertOwnerShareFlag } from "./SharedExpertHint";
import RemoteExpertHint from "./RemoteExpertHint";
import SessionShareMark from "./SessionShareMark";
import SessionWorkStatusIcon from "./SessionWorkStatusIcon";
import TeamChatBadge from "./TeamChatBadge";
import { isTeamAgent } from "../../../utils/teamAgent";
import ExpertNameLabel from "./ExpertNameLabel";
import ExpertNavActions, { ExpertPinMark } from "./ExpertNavActions";
import ChatEditExpertDrawer, {
  canEditExpertFromChat,
} from "./ChatEditExpertDrawer";
import styles from "../index.module.less";

/** Default preview size per expert in minimal nav (matches session page size). */
export const MINIMAL_AGENT_SESSION_PREVIEW = 10;

function storedPreviewLimit(
  limits: Record<string, number>,
  agentId: string,
): number {
  return limits[agentId] ?? MINIMAL_AGENT_SESSION_PREVIEW;
}

/** One extra row tells us whether another page exists, same as the classic list. */
async function fetchAgentPreview(
  agentId: string,
  limit: number,
): Promise<{ sessions: Session[]; hasMore: boolean }> {
  const rows = await octopThreadsApi.list(agentId, limit + 1);
  return {
    sessions: sortSessions(rows.slice(0, limit).map(toSession)),
    hasMore: rows.length > limit,
  };
}

const FOLDER_COLLAPSED_KEY = "octop:minimal-agent-folders-collapsed";

/** Sessions without a workspace, and default-home experts, share this project. */
const DEFAULT_PROJECT_KEY = "default";

function loadCollapsedFolders(): Set<string> {
  try {
    const raw = localStorage.getItem(FOLDER_COLLAPSED_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return new Set(parsed.filter((x): x is string => typeof x === "string"));
    }
  } catch {
    /* ignore */
  }
  return new Set();
}

function saveCollapsedFolders(collapsed: Set<string>) {
  try {
    localStorage.setItem(FOLDER_COLLAPSED_KEY, JSON.stringify([...collapsed]));
  } catch {
    /* ignore */
  }
}

interface MinimalAgentSessionNavProps {
  agents: OctopAgent[];
  activeId: string | null;
  activeAgentId: string | null;
  /** Live sessions for the currently active agent (keeps nav in sync). */
  activeSessions: Session[];
  onSelect: (sessionId: string, agentId: string) => void;
  onAgentSelect: (agentId: string) => void;
  /** Start a fresh (unsaved) chat with the given expert. */
  onNewChat: (agentId: string, projectId?: string | null) => void;
  /** Open the folder picker that creates a workspace-backed project. */
  onNewProject?: () => void;
  onDeleteActive: (
    id: string,
    compact: boolean,
  ) => void | Promise<boolean | null | void>;
  onRenameActive: (id: string, name: string) => void;
  onPinActive: (id: string, pinned: boolean) => void;
  onFork: (id: string, agentId?: string | null) => void;
  activeForkDisabled?: boolean;
  activeForkDisabledHint?: string;
  /** Experts that exist but cannot chat yet (stopped / model not configured). */
  unreadyExperts?: number;
}

const PreviewSessionRow = memo(function PreviewSessionRow({
  session,
  agent,
  isActive,
  workStatus,
  onSelect,
  onDelete,
  onRename,
  onPin,
  onFork,
  onContribute,
  shareable,
  forkDisabled,
  forkDisabledHint,
}: {
  session: Session;
  /** Set in the flat "sessions" list: shows which expert owns this thread. */
  agent?: OctopAgent;
  isActive: boolean;
  workStatus: SessionWorkStatus;
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
}) {
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
        styles.sessionRowCompact,
        isActive && styles.sessionRowActive,
        session.pinned && styles.sessionRowPinned,
      )}
      onClick={() => {
        if (!isEditing) onSelect(session.id);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !isEditing) onSelect(session.id);
      }}
    >
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
          <span className={styles.sessionRowLead}>
            <SessionWorkStatusIcon status={workStatus} />
          </span>
          <span className={styles.sessionRowTitleGroup}>
            <span className={styles.sessionRowTitle}>{session.name}</span>
            <SessionShareMark
              contributed={session.contributed}
              owned={session.owned}
            />
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

export default function MinimalAgentSessionNav({
  agents,
  activeId,
  activeAgentId,
  activeSessions,
  onSelect,
  onAgentSelect,
  onNewChat,
  onNewProject,
  onDeleteActive,
  onRenameActive,
  onPinActive,
  onFork,
  activeForkDisabled,
  activeForkDisabledHint,
  unreadyExperts = 0,
}: MinimalAgentSessionNavProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [byAgent, setByAgent] = useState<Record<string, Session[]>>({});
  const [hasMoreByAgent, setHasMoreByAgent] = useState<Record<string, boolean>>(
    {},
  );
  const [loadingMoreByAgent, setLoadingMoreByAgent] = useState<
    Record<string, boolean>
  >({});
  const limitsRef = useRef<Record<string, number>>({});
  const requestedLimitsRef = useRef<Record<string, number>>({});
  const requestIdsRef = useRef<Record<string, number>>({});
  const loadingMoreRef = useRef<Set<string>>(new Set());
  const rosterRef = useRef("");
  const liveWorkingIds = useSessionWorkIds();
  const [loading, setLoading] = useState(false);
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(() =>
    loadCollapsedFolders(),
  );
  const agentKey = useMemo(
    () =>
      [...agents]
        .map((a) => a.agent_id)
        .sort()
        .join(","),
    [agents],
  );

  const [searchQuery, setSearchQuery] = useState("");
  const [editAgent, setEditAgent] = useState<OctopAgent | null>(null);
  const [showingHidden, setShowingHidden] = useState(false);
  const [navScope, setNavScope] = useState<ChatNavScope>(initialChatNavScope);
  // "projects" groups by the workspace each expert already runs in, so
  // workspaces are only resolved while that tab is open.
  const workspaces = useAgentWorkspaces(agents, navScope === "projects");
  const { pinnedIds, isPinned, togglePin } = usePinnedExperts();
  const { filterVisible, pickHidden, hide, unhide, canHide } =
    useHiddenSharedExperts();
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
  const searching = searchQuery.trim().length > 0;
  const catalog = useExpertSessionCatalog(
    sortedAgents,
    searching || navScope === "projects",
  );
  const visibleAgents = useMemo(() => {
    if (!searching) return sortedAgents;
    return sortedAgents.filter((agent) => {
      const own =
        agent.agent_id === activeAgentId && activeSessions.length > 0
          ? activeSessions
          : catalog.byAgent[agent.agent_id] ?? byAgent[agent.agent_id] ?? [];
      return expertVisibleInNavSearch(
        agent.name,
        own.map((session) => session.name),
        searchQuery,
      );
    });
  }, [
    activeAgentId,
    activeSessions,
    byAgent,
    catalog.byAgent,
    searchQuery,
    searching,
    sortedAgents,
  ]);
  const listedHiddenAgents = useMemo(() => {
    if (!showingHidden) return [];
    const shown = new Set(visibleAgents.map((agent) => agent.agent_id));
    return hiddenAgents.filter((agent) => {
      if (shown.has(agent.agent_id)) return false;
      if (!searching) return true;
      return matchesNavQuery(agent.name, searchQuery);
    });
  }, [hiddenAgents, searchQuery, searching, showingHidden, visibleAgents]);
  const navBlocks = useMemo(() => {
    const blocks: Array<
      | { kind: "agent"; agent: OctopAgent; key: string }
      | { kind: "toggle"; key: string }
    > = visibleAgents.map((agent) => ({
      kind: "agent",
      agent,
      key: agent.agent_id,
    }));
    if (hiddenAgents.length === 0) return blocks;
    blocks.push({ kind: "toggle", key: "hidden-toggle" });
    if (showingHidden) {
      for (const agent of listedHiddenAgents) {
        blocks.push({
          kind: "agent",
          agent,
          key: `hidden-${agent.agent_id}`,
        });
      }
    }
    return blocks;
  }, [hiddenAgents.length, listedHiddenAgents, showingHidden, visibleAgents]);

  /** Sessions already loaded for one expert (live store wins for the active one). */
  const previewFor = useCallback(
    (agent: OctopAgent): Session[] =>
      agent.agent_id === activeAgentId && activeSessions.length > 0
        ? activeSessions
        : byAgent[agent.agent_id] ?? [],
    [activeAgentId, activeSessions, byAgent],
  );

  /**
   * "sessions" tab: one recency-ordered list across experts. Preview pages are
   * already fetched per expert, so this needs no extra requests.
   */
  const flatEntries = useMemo(() => {
    if (navScope !== "sessions") return [];
    const q = searchQuery.trim().toLowerCase();
    const rows: Array<{ session: Session; agent: OctopAgent }> = [];
    for (const agent of visibleAgents) {
      const agentMatches = q.length > 0 && agent.name.toLowerCase().includes(q);
      for (const session of previewFor(agent)) {
        if (q && !agentMatches && !session.name.toLowerCase().includes(q)) {
          continue;
        }
        rows.push({ session, agent });
      }
    }
    rows.sort((a, b) => compareSessionsByRecency(a.session, b.session));
    return rows;
  }, [navScope, previewFor, searchQuery, visibleAgents]);

  /**
   * "projects" tab: one project per ``workspace_dir``. Experts bound to the same
   * folder share a project; experts with no binding (or only the auto-created
   * agent home) land in the default workspace project so nothing drops out.
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
    for (const agent of visibleAgents) {
      const dir = workspaces.byAgent[agent.agent_id]?.workspaceDir ?? null;
      const attributed =
        Boolean(dir) && !isDefaultWorkspacePath(dir, workspaces.agentsRoot);
      const legacyKey =
        attributed && dir
          ? `ws:${normalizeWorkspaceDir(dir)}`
          : DEFAULT_PROJECT_KEY;
      const agentMatches = q.length > 0 && agent.name.toLowerCase().includes(q);
      for (const session of previewFor(agent)) {
        if (q && !agentMatches && !session.name.toLowerCase().includes(q)) {
          continue;
        }
        // Migrated conversations group by the projects table; un-migrated ones
        // keep the legacy workspace_dir grouping until the upgrade runs.
        const projectId = session.projectId ?? null;
        const key = projectId ? `prj:${projectId}` : legacyKey;
        const projectDir = projectId
          ? session.workspaceDir ?? dir
          : attributed
          ? dir
          : null;
        let group = groups.get(key);
        if (!group) {
          group = {
            key,
            title: projectId
              ? session.projectName ||
                t("chat.workspaceDefaultName", "默认工作区")
              : attributed && dir
              ? workspaceBasename(dir)
              : t("chat.workspaceDefaultName", "默认工作区"),
            dir: projectDir,
            isDefault: !projectId && !attributed,
            agentId: agent.agent_id,
            projectId,
            entries: [],
          };
          groups.set(key, group);
        } else if (agent.agent_id === activeAgentId) {
          group.agentId = agent.agent_id;
        }
        group.entries.push({ session, agent });
      }
      // Keep parity with the classic sidebar: experts with a dedicated folder
      // still show that folder as a project before it has any conversation.
      if (!q && previewFor(agent).length === 0 && !groups.has(legacyKey)) {
        groups.set(legacyKey, {
          key: legacyKey,
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
    const rows = [...groups.values()];
    for (const group of rows) {
      group.entries.sort((a, b) =>
        compareSessionsByRecency(a.session, b.session),
      );
    }
    rows.sort((a, b) => {
      if (a.isDefault !== b.isDefault) return a.isDefault ? 1 : -1;
      const ta = a.entries[0]?.session.updatedAt;
      const tb = b.entries[0]?.session.updatedAt;
      if (ta || tb) {
        return (tb ? Date.parse(tb) : 0) - (ta ? Date.parse(ta) : 0);
      }
      return a.title.localeCompare(b.title);
    });
    return rows;
  }, [
    activeAgentId,
    navScope,
    previewFor,
    searchQuery,
    t,
    visibleAgents,
    workspaces.agentsRoot,
    workspaces.byAgent,
  ]);

  /** Wait for every listed expert's workspace before grouping. */
  const workspacesReady = useMemo(
    () =>
      workspaces.rootReady &&
      visibleAgents.every((agent) => workspaces.byAgent[agent.agent_id]),
    [visibleAgents, workspaces.byAgent, workspaces.rootReady],
  );

  /** Project holding the open conversation; expanded by default. */
  const currentProjectKey = useMemo(() => {
    if (!activeAgentId) return null;
    const activeAgent = visibleAgents.find(
      (agent) => agent.agent_id === activeAgentId,
    );
    const activeSession = activeAgent
      ? previewFor(activeAgent).find((session) => session.isActive)
      : undefined;
    if (activeSession?.projectId) return `prj:${activeSession.projectId}`;
    const dir = workspaces.byAgent[activeAgentId]?.workspaceDir ?? null;
    if (!dir || isDefaultWorkspacePath(dir, workspaces.agentsRoot)) {
      return DEFAULT_PROJECT_KEY;
    }
    return `ws:${normalizeWorkspaceDir(dir)}`;
  }, [
    activeAgentId,
    previewFor,
    visibleAgents,
    workspaces.agentsRoot,
    workspaces.byAgent,
  ]);

  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(
    () => new Set(),
  );
  useEffect(() => {
    if (!currentProjectKey) return;
    setExpandedProjects((prev) =>
      prev.has(currentProjectKey) ? prev : new Set(prev).add(currentProjectKey),
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
  const [projectLimits, setProjectLimits] = useState<Record<string, number>>(
    {},
  );
  const revealMoreProjectSessions = useCallback((key: string) => {
    setProjectLimits((prev) => ({
      ...prev,
      [key]:
        (prev[key] ?? MINIMAL_AGENT_SESSION_PREVIEW) +
        MINIMAL_AGENT_SESSION_PREVIEW,
    }));
  }, []);

  // Ensure the active expert folder stays open.
  useEffect(() => {
    if (!activeAgentId) return;
    setCollapsedFolders((prev) => {
      if (!prev.has(activeAgentId)) return prev;
      const next = new Set(prev);
      next.delete(activeAgentId);
      saveCollapsedFolders(next);
      return next;
    });
  }, [activeAgentId]);

  const toggleFolder = useCallback((agentId: string) => {
    setCollapsedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      saveCollapsedFolders(next);
      return next;
    });
  }, []);

  const openFolderAndSelect = useCallback(
    (agentId: string) => {
      setCollapsedFolders((prev) => {
        if (!prev.has(agentId)) return prev;
        const next = new Set(prev);
        next.delete(agentId);
        saveCollapsedFolders(next);
        return next;
      });
      onAgentSelect(agentId);
    },
    [onAgentSelect],
  );

  const applyPreview = useCallback(
    (
      agentId: string,
      page: { sessions: Session[]; hasMore: boolean },
      limit: number,
    ) => {
      limitsRef.current[agentId] = limit;
      setByAgent((prev) => ({ ...prev, [agentId]: page.sessions }));
      setHasMoreByAgent((prev) => ({ ...prev, [agentId]: page.hasMore }));
    },
    [],
  );

  const refreshAgentPreview = useCallback(
    async (agentId: string, limit?: number) => {
      if (!agentId) return;
      const pageSize =
        limit ??
        requestedLimitsRef.current[agentId] ??
        storedPreviewLimit(limitsRef.current, agentId);
      const requestId = (requestIdsRef.current[agentId] ?? 0) + 1;
      requestIdsRef.current[agentId] = requestId;
      try {
        const page = await fetchAgentPreview(agentId, pageSize);
        if (requestIdsRef.current[agentId] !== requestId) return;
        if (!rosterRef.current.split(",").includes(agentId)) return;
        applyPreview(agentId, page, pageSize);
      } catch {
        /* keep the previous page; the expand button stays clickable */
      }
    },
    [applyPreview],
  );

  const loadMore = useCallback(
    async (agentId: string) => {
      if (loadingMoreRef.current.has(agentId)) return;
      loadingMoreRef.current.add(agentId);
      const limit =
        storedPreviewLimit(limitsRef.current, agentId) +
        MINIMAL_AGENT_SESSION_PREVIEW;
      requestedLimitsRef.current[agentId] = limit;
      setLoadingMoreByAgent((prev) => ({ ...prev, [agentId]: true }));
      try {
        await refreshAgentPreview(agentId, limit);
      } finally {
        delete requestedLimitsRef.current[agentId];
        loadingMoreRef.current.delete(agentId);
        setLoadingMoreByAgent((prev) => ({ ...prev, [agentId]: false }));
      }
    },
    [refreshAgentPreview],
  );

  // Fetch preview threads for every expert (independent of classic session store).
  // Keep each expert's already-expanded page size across roster refreshes.
  useEffect(() => {
    rosterRef.current = agentKey;
    if (!agentKey) {
      setByAgent({});
      setHasMoreByAgent({});
      setLoading(false);
      return;
    }
    const ids = new Set(agentKey.split(",").filter(Boolean));
    setByAgent((prev) => {
      if (Object.keys(prev).every((id) => ids.has(id))) return prev;
      const next: Record<string, Session[]> = {};
      for (const id of ids) {
        if (prev[id]) next[id] = prev[id];
      }
      return next;
    });
    setHasMoreByAgent((prev) => {
      if (Object.keys(prev).every((id) => ids.has(id))) return prev;
      const next: Record<string, boolean> = {};
      for (const id of ids) {
        if (id in prev) next[id] = prev[id];
      }
      return next;
    });
    let cancelled = false;
    setLoading(true);
    void (async () => {
      await Promise.all([...ids].map((id) => refreshAgentPreview(id)));
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [agentKey, refreshAgentPreview]);

  // Keep the active expert aligned with the live session store.
  // Skip empty lists — a host that passes [] must not wipe fetched previews
  // when the user selects a session. Merge instead of replacing so an
  // expanded page is not clipped back to the live first page.
  useEffect(() => {
    if (!activeAgentId || activeSessions.length === 0) return;
    const agentId = activeAgentId;
    setByAgent((prev) => {
      const limit = storedPreviewLimit(limitsRef.current, agentId);
      const merged = new Map(
        (prev[agentId] ?? []).map((session) => [session.id, session]),
      );
      for (const session of activeSessions) merged.set(session.id, session);
      return {
        ...prev,
        [agentId]: sortSessions([...merged.values()]).slice(0, limit),
      };
    });
  }, [activeAgentId, activeSessions]);

  useEffect(() => {
    return onSessionEvent((event) => {
      if (event.kind === "sessionDeleted") {
        const { sessionId } = event;
        setByAgent((prev) => {
          const next: Record<string, Session[]> = {};
          for (const [aid, list] of Object.entries(prev)) {
            next[aid] = list.filter((s) => s.id !== sessionId);
          }
          return next;
        });
        return;
      }
      const target = event.agentId || activeAgentId;
      if (target) void refreshAgentPreview(target);
    });
  }, [activeAgentId, refreshAgentPreview]);

  const patchLocal = useCallback(
    (agentId: string, updater: (prev: Session[]) => Session[]) => {
      setByAgent((prev) => ({
        ...prev,
        [agentId]: sortSessions(updater(prev[agentId] ?? [])).slice(
          0,
          storedPreviewLimit(limitsRef.current, agentId),
        ),
      }));
      catalog.patch(agentId, updater);
    },
    [catalog.patch],
  );

  const handleDelete = useCallback(
    async (agentId: string, sessionId: string, compact: boolean) => {
      if (agentId === activeAgentId) {
        const deleted = await onDeleteActive(sessionId, compact);
        if (deleted !== true) return deleted;
        patchLocal(agentId, (prev) => prev.filter((s) => s.id !== sessionId));
        return true;
      }
      const deleted = await deleteConversation(agentId, sessionId, compact, t);
      if (deleted !== true) return deleted;
      patchLocal(agentId, (prev) => prev.filter((s) => s.id !== sessionId));
      return true;
    },
    [activeAgentId, onDeleteActive, patchLocal, t],
  );

  const handleRename = useCallback(
    (agentId: string, sessionId: string, name: string) => {
      const next = formatThreadTitle(name) || name.trim();
      if (!next) return;
      if (agentId === activeAgentId) {
        onRenameActive(sessionId, next);
      } else {
        void octopThreadsApi.rename(agentId, sessionId, next).catch(() => {});
      }
      patchLocal(agentId, (prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, name: next } : s)),
      );
    },
    [activeAgentId, onRenameActive, patchLocal],
  );

  const handlePin = useCallback(
    (agentId: string, sessionId: string, pinned: boolean) => {
      if (agentId === activeAgentId) {
        onPinActive(sessionId, pinned);
      } else {
        void octopThreadsApi
          .patch(agentId, sessionId, { pinned })
          .catch(() => {});
      }
      patchLocal(agentId, (prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, pinned } : s)),
      );
    },
    [activeAgentId, onPinActive, patchLocal],
  );

  const handleContribute = useCallback(
    (agentId: string, sessionId: string, contributed: boolean) => {
      void saveSessionShared(
        agentId,
        sessionId,
        contributed,
        () => {
          patchLocal(agentId, (prev) =>
            prev.map((session) =>
              session.id === sessionId ? { ...session, contributed } : session,
            ),
          );
        },
        t("chat.shareFailed", "没能改共享状态，请再试一次"),
      );
    },
    [patchLocal, t],
  );

  /** Flat rows (sessions / projects) share this wiring. */
  const renderPreviewRow = (session: Session, agent: OctopAgent) => (
    <PreviewSessionRow
      key={`${agent.agent_id}:${session.id}`}
      session={session}
      agent={agent}
      isActive={session.id === activeId}
      workStatus={resolveSessionWorkStatus(session, liveWorkingIds)}
      onSelect={(id) => onSelect(id, agent.agent_id)}
      onDelete={(id, compact) => handleDelete(agent.agent_id, id, compact)}
      onRename={(id, name) => handleRename(agent.agent_id, id, name)}
      onPin={(id, pinned) => handlePin(agent.agent_id, id, pinned)}
      onContribute={(id, contributed) =>
        handleContribute(agent.agent_id, id, contributed)
      }
      shareable={Boolean(agent.is_shared)}
      onFork={(id) => onFork(id, agent.agent_id)}
      forkDisabled={session.id === activeId ? activeForkDisabled : undefined}
      forkDisabledHint={
        session.id === activeId ? activeForkDisabledHint : undefined
      }
    />
  );

  if (agents.length === 0) {
    // The rail only lists experts that can chat right now, so an empty list has
    // two very different causes. Never answer "create your first expert" while
    // the user still has experts (and their history) waiting to start.
    const hasUnreadyExperts = unreadyExperts > 0;
    return (
      <div className={styles.sessionEmptyAgents}>
        <p className={styles.sessionEmptyAgentsText}>
          {hasUnreadyExperts
            ? t("chat.noChattableAgentsHint")
            : t("chat.noAgentsHint")}
        </p>
        <button
          type="button"
          className={styles.sessionEmptyAgentsLink}
          onClick={() => navigate("/experts")}
        >
          {hasUnreadyExperts ? t("chat.goToExperts") : t("chat.createExpert")}
        </button>
      </div>
    );
  }

  return (
    <div className={cx(styles.sessionList, styles.minimalAgentNav)}>
      <ChatEditExpertDrawer
        agent={editAgent}
        onClose={() => setEditAgent(null)}
      />
      <div className={styles.sessionSearchWrap}>
        <Search
          size={14}
          className={styles.sessionSearchIcon}
          strokeWidth={2}
        />
        <input
          type="search"
          className={styles.sessionSearchInput}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t("chat.searchSessions", "搜索会话")}
          aria-label={t("chat.searchSessions", "搜索会话")}
        />
      </div>
      <ChatNavScopeTabs value={navScope} onChange={setNavScope} />
      <ChatNavCloudEntry
        active={navScope === "cloud"}
        count={
          agents.filter((agent) => matchesChatNavScope(agent, "cloud")).length
        }
        onOpen={() => setNavScope("cloud")}
        onClose={() => setNavScope("sessions")}
      />
      {navScope !== "sessions" &&
      navScope !== "projects" &&
      visibleAgents.length === 0 &&
      (searching || loading || hiddenAgents.length === 0) ? (
        searching ? (
          <div className={styles.minimalAgentEmpty}>
            {catalog.loading
              ? t("common.loading")
              : t("chat.noSearchResults", "没有匹配的会话")}
          </div>
        ) : (
          <ChatNavScopeEmpty scope={navScope} />
        )
      ) : null}
      {navScope === "sessions" ? (
        <div className={styles.minimalAgentSessions}>
          {flatEntries.length === 0 ? (
            <div className={styles.minimalAgentEmpty}>
              {searching
                ? t("chat.noSearchResults", "没有匹配的会话")
                : loading
                ? t("common.loading")
                : t("chat.noSessionsYet", "直接发消息即可开始对话")}
            </div>
          ) : (
            <>
              {flatEntries.map(({ session, agent }) =>
                renderPreviewRow(session, agent),
              )}
              {visibleAgents.some((agent) => hasMoreByAgent[agent.agent_id]) ? (
                <button
                  type="button"
                  className={styles.sessionLoadMore}
                  onClick={() => {
                    for (const agent of visibleAgents) {
                      if (hasMoreByAgent[agent.agent_id]) {
                        void loadMore(agent.agent_id);
                      }
                    }
                  }}
                >
                  {t("chat.expandMore", "展开更多")}
                </button>
              ) : null}
            </>
          )}
        </div>
      ) : navScope === "projects" ? (
        <div className={styles.minimalAgentSessions}>
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
          {!workspacesReady || loading ? (
            <div className={styles.minimalAgentEmpty}>
              {t("common.loading")}
            </div>
          ) : projectGroups.length === 0 ? (
            <div className={styles.minimalAgentEmpty}>
              {t("chat.noSearchResults", "没有匹配的会话")}
            </div>
          ) : (
            projectGroups.map((group) => {
              const open = expandedProjects.has(group.key);
              const limit =
                projectLimits[group.key] ?? MINIMAL_AGENT_SESSION_PREVIEW;
              const shown = group.entries.slice(0, limit);
              return (
                <div key={group.key}>
                  <button
                    type="button"
                    className={styles.sessionProjectHeader}
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
                    <span className={styles.sessionProjectCount}>
                      {group.entries.length}
                    </span>
                  </button>
                  {open ? (
                    group.entries.length === 0 ? (
                      <div className={styles.sessionProjectEmpty}>
                        <span>
                          {t("chat.projectEmptyHint", "这个项目下还没有会话")}
                        </span>
                        <button
                          type="button"
                          className={styles.sessionEmptyAgentsLink}
                          onClick={() =>
                            onNewChat(group.agentId, group.projectId)
                          }
                        >
                          {t("chat.palette.newChat", "新建会话")}
                        </button>
                      </div>
                    ) : (
                      <>
                        {shown.map(({ session, agent }) =>
                          renderPreviewRow(session, agent),
                        )}
                        {group.entries.length > shown.length ? (
                          <button
                            type="button"
                            className={styles.sessionLoadMore}
                            onClick={() => revealMoreProjectSessions(group.key)}
                          >
                            {t("chat.expandMore", "展开更多")}
                          </button>
                        ) : null}
                      </>
                    )
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      ) : (
        navBlocks.map((block) => {
          if (block.kind === "toggle") {
            return (
              <HiddenExpertsToggle
                key={block.key}
                expanded={showingHidden}
                count={hiddenAgents.length}
                onToggle={() => setShowingHidden((open) => !open)}
              />
            );
          }
          const agent = block.agent;
          const preview = byAgent[agent.agent_id] ?? [];
          const catalogList = catalog.byAgent[agent.agent_id] ?? [];
          const live =
            agent.agent_id === activeAgentId && activeSessions.length > 0
              ? activeSessions
              : null;
          const source = searching
            ? live && live.length >= catalogList.length
              ? live
              : catalogList.length > 0
              ? catalogList
              : preview
            : preview;
          const list = searching
            ? source.filter((session) =>
                matchesNavQuery(session.name, searchQuery),
              )
            : source;
          const ready = isAgentChatReady(agent.state);
          const expanded = searching
            ? list.length > 0
            : !collapsedFolders.has(agent.agent_id);

          return (
            <section key={block.key} className={styles.minimalAgentSection}>
              <div className={styles.minimalAgentHeader}>
                <span className={styles.minimalAgentIconSlot}>
                  <SharedExpertHint
                    agent={agent}
                    className={styles.minimalAgentAvatarHost}
                  >
                    <span
                      className={styles.minimalAgentAvatar}
                      style={{
                        color: agent.color || "var(--fn-text-tertiary)",
                        background: `${agent.color || "#6366f1"}14`,
                      }}
                      aria-hidden
                    >
                      <ExpertIcon
                        iconUrl={agent.icon_url}
                        iconName={agent.icon_name}
                        size={agent.icon_url?.trim() ? 22 : 14}
                      />
                    </span>
                  </SharedExpertHint>
                  <button
                    type="button"
                    className={styles.minimalAgentChevronBtn}
                    aria-expanded={expanded}
                    aria-label={
                      expanded
                        ? t("nav.collapseSidebar")
                        : t("nav.expandSidebar")
                    }
                    onClick={() => toggleFolder(agent.agent_id)}
                  >
                    <ChevronRight
                      size={14}
                      strokeWidth={2}
                      className={cx(
                        styles.minimalAgentChevron,
                        expanded && styles.minimalAgentChevronOpen,
                      )}
                      aria-hidden
                    />
                  </button>
                </span>
                <button
                  type="button"
                  className={styles.minimalAgentFolderBtn}
                  onClick={() => openFolderAndSelect(agent.agent_id)}
                >
                  <span className={styles.agentNameCluster}>
                    <ExpertNameLabel
                      name={agent.name}
                      className={styles.minimalAgentName}
                    />
                    <ExpertOwnerShareFlag agent={agent} />
                    <ExpertPinMark pinned={isPinned(agent.agent_id)} />
                    <TeamChatBadge agent={agent} compact />
                    <RemoteExpertHint agent={agent} compact />
                  </span>
                </button>
                <AgentUnreadBadge
                  count={agent.unread_count ?? 0}
                  onOpen={() => {
                    void openAgentUnread(agent.agent_id, list, onSelect);
                  }}
                />
                <ExpertNavActions
                  variant="minimal"
                  pinned={isPinned(agent.agent_id)}
                  onTogglePin={() => togglePin(agent.agent_id)}
                  onNewChat={() => onNewChat(agent.agent_id)}
                  onEdit={
                    canEditExpertFromChat(agent)
                      ? () => setEditAgent(agent)
                      : undefined
                  }
                  editingTeam={isTeamAgent(agent)}
                  onHide={
                    canHide(agent) &&
                    !hiddenAgents.some((row) => row.agent_id === agent.agent_id)
                      ? () => hide(agent.agent_id)
                      : undefined
                  }
                  onUnhide={
                    hiddenAgents.some((row) => row.agent_id === agent.agent_id)
                      ? () => unhide(agent.agent_id)
                      : undefined
                  }
                />
              </div>

              {expanded ? (
                <div className={styles.minimalAgentSessions}>
                  {!ready ? (
                    <div className={styles.minimalAgentEmpty}>
                      {t("chat.agentNotRunningHint")}
                    </div>
                  ) : loading && list.length === 0 ? (
                    <div className={styles.minimalAgentEmpty}>
                      {t("common.loading")}
                    </div>
                  ) : list.length === 0 ? (
                    <div className={styles.minimalAgentEmpty}>
                      {t("chat.noSessionsYet", "直接发消息即可开始对话")}
                    </div>
                  ) : (
                    <>
                      {list.map((session) => (
                        <PreviewSessionRow
                          key={session.id}
                          session={session}
                          isActive={session.id === activeId}
                          workStatus={resolveSessionWorkStatus(
                            session,
                            liveWorkingIds,
                          )}
                          onSelect={(id) => onSelect(id, agent.agent_id)}
                          onDelete={(id, compact) =>
                            handleDelete(agent.agent_id, id, compact)
                          }
                          onRename={(id, name) =>
                            handleRename(agent.agent_id, id, name)
                          }
                          onPin={(id, pinned) =>
                            handlePin(agent.agent_id, id, pinned)
                          }
                          onContribute={(id, contributed) =>
                            handleContribute(agent.agent_id, id, contributed)
                          }
                          shareable={Boolean(agent.is_shared)}
                          onFork={(id) => onFork(id, agent.agent_id)}
                          forkDisabled={
                            session.id === activeId
                              ? activeForkDisabled
                              : undefined
                          }
                          forkDisabledHint={
                            session.id === activeId
                              ? activeForkDisabledHint
                              : undefined
                          }
                        />
                      ))}
                      {!searching && hasMoreByAgent[agent.agent_id] ? (
                        <button
                          type="button"
                          className={styles.sessionLoadMore}
                          onClick={() => void loadMore(agent.agent_id)}
                          disabled={loadingMoreByAgent[agent.agent_id]}
                        >
                          {loadingMoreByAgent[agent.agent_id]
                            ? t("common.loading")
                            : t("chat.expandMore", "展开更多")}
                        </button>
                      ) : null}
                    </>
                  )}
                </div>
              ) : null}
            </section>
          );
        })
      )}
    </div>
  );
}
