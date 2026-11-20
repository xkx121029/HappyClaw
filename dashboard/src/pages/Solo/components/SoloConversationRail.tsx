import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, FileText, Plus, Search } from "lucide-react";
import cx from "classnames";
import type { OctopAgent } from "../../../context/AgentContext";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import type { Session } from "../../Chat/hooks/useSessions";
import {
  formatServerHourMinute,
  formatServerYmd,
} from "../../../utils/formatMessageTime";
import SoloMenu from "./SoloMenu";
import styles from "../solo.module.less";

interface SoloConversationRailProps {
  agents: OctopAgent[];
  agentId: string | null;
  agentReady: boolean;
  onSelectAgent: (agentId: string) => void;
  sessions: Session[];
  sessionsLoading: boolean;
  activeThreadId: string | null;
  onSelectThread: (threadId: string) => void;
  onNewChat: () => void;
  onOpenFiles: () => void;
  streaming: boolean;
}

function formatSessionTime(updatedAt: string | null, timeZone: string): string {
  if (!updatedAt) return "";
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return "";
  return `${formatServerYmd(date, timeZone).slice(5)} ${formatServerHourMinute(
    date,
    timeZone,
  )}`;
}

/**
 * 对话面板（对应参照稿左栏）：状态点 + 专家入口 + 新任务/打开文件 + 会话列表。
 * 选中状态只属于 SOLO，不读写主模式的 activeAgent。
 */
export default function SoloConversationRail({
  agents,
  agentId,
  agentReady,
  onSelectAgent,
  sessions,
  sessionsLoading,
  activeThreadId,
  onSelectThread,
  onNewChat,
  onOpenFiles,
  streaming,
}: SoloConversationRailProps) {
  const { t } = useTranslation();
  const timeZone = useServerTimezone();
  const [agentMenuOpen, setAgentMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");

  const currentAgent = useMemo(
    () => agents.find((agent) => agent.agent_id === agentId) ?? null,
    [agents, agentId],
  );

  const agentItems = useMemo(
    () =>
      [...agents]
        .sort((a, b) => {
          const readyDiff =
            Number(b.state === "running") - Number(a.state === "running");
          return readyDiff !== 0 ? readyDiff : a.name.localeCompare(b.name);
        })
        .map((agent) => ({
          key: agent.agent_id,
          label: agent.name,
          active: agent.agent_id === agentId,
        })),
    [agents, agentId],
  );

  const visibleSessions = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return sessions;
    return sessions.filter((session) =>
      session.name.toLowerCase().includes(keyword),
    );
  }, [sessions, search]);

  const searchLabel = t("solo.searchSessions", {
    defaultValue: t("solo.sessions"),
  });

  return (
    <div className={styles.sidePanel}>
      <div className={styles.sideHead}>
        <span
          className={cx(
            styles.sideStatus,
            streaming && styles.sideStatusBusy,
            !agentReady && styles.sideStatusOff,
          )}
          aria-hidden
        />
        <div
          className={styles.menuAnchor}
          style={{ flex: 1, minWidth: 0 }}
        >
          <button
            type="button"
            className={styles.sideAgentButton}
            aria-haspopup="menu"
            aria-expanded={agentMenuOpen}
            onClick={() => setAgentMenuOpen((open) => !open)}
          >
            <span className={styles.projectSelectName}>
              {currentAgent?.name ?? t("solo.noAgent")}
            </span>
            <ChevronDown size={10} />
          </button>
          {agentMenuOpen ? (
            <SoloMenu
              items={agentItems}
              onSelect={(key) => {
                setAgentMenuOpen(false);
                onSelectAgent(key);
              }}
              onClose={() => setAgentMenuOpen(false)}
              ariaLabel={t("solo.expert")}
            />
          ) : null}
        </div>
      </div>

      <div className={styles.sideMeta}>
        {agentReady ? t("solo.ready") : t("solo.agentStoppedShort")} ·{" "}
        {sessions.length} {t("solo.sessions")}
      </div>

      <button type="button" className={styles.newTask} onClick={onNewChat}>
        <Plus size={14} />
        <span>{t("solo.newTask", { defaultValue: t("solo.newChat") })}</span>
        <span className={styles.newTaskKey}>Ctrl+Alt+N</span>
      </button>

      <button type="button" className={styles.sideItem} onClick={onOpenFiles}>
        <FileText size={14} />
        <span>{t("solo.openFiles", { defaultValue: t("solo.files") })}</span>
      </button>

      <div className={styles.sideSectionHead}>
        <span>{t("solo.sessions")}</span>
        <span className={styles.sideCount}>{sessions.length}</span>
        <span className={styles.sideSpacer} />
        <button
          type="button"
          className={styles.sideIconButton}
          aria-label={searchLabel}
          aria-pressed={searchOpen}
          onClick={() => setSearchOpen((open) => !open)}
        >
          <Search size={13} />
        </button>
      </div>

      {searchOpen ? (
        <div className={styles.sideSearchRow}>
          <input
            type="text"
            className={styles.sideSearchInput}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={searchLabel}
            aria-label={searchLabel}
          />
        </div>
      ) : null}

      <div className={styles.sessionList}>
        {sessionsLoading && sessions.length === 0 ? (
          <div className={styles.sideEmpty}>{t("solo.sessionsLoading")}</div>
        ) : visibleSessions.length === 0 ? (
          <div className={styles.sideEmpty}>{t("solo.sessionsEmpty")}</div>
        ) : (
          visibleSessions.map((session) => {
            const active = session.id === activeThreadId;
            return (
              <button
                type="button"
                key={session.id}
                className={cx(
                  styles.sessionItem,
                  active && styles.sessionItemActive,
                )}
                aria-current={active ? "true" : undefined}
                onClick={() => onSelectThread(session.id)}
                title={session.name}
              >
                <div className={styles.sessionName}>
                  <span className={styles.sessionDot} aria-hidden />
                  {session.name}
                </div>
                <div className={styles.sessionTime}>
                  {formatSessionTime(session.updatedAt, timeZone)}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
