import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Select, Tooltip } from "antd";
import {
  ChevronLeft,
  ChevronRight,
  MessageSquarePlus,
  MessagesSquare,
} from "lucide-react";
import cx from "classnames";
import type { OctopAgent } from "../../../context/AgentContext";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import type { Session } from "../../Chat/hooks/useSessions";
import {
  formatServerHourMinute,
  formatServerYmd,
} from "../../../utils/formatMessageTime";
import styles from "../solo.module.less";

interface SoloConversationRailProps {
  agents: OctopAgent[];
  activeAgentId: string | null;
  onSelectAgent: (agentId: string) => void;
  sessions: Session[];
  sessionsLoading: boolean;
  activeThreadId: string | null;
  onSelectThread: (threadId: string) => void;
  onNewChat: () => void;
  collapsed: boolean;
  /** 容器过窄时禁止展开，按钮给出明确提示而不是静默失效。 */
  toggleDisabled?: boolean;
  onToggleCollapsed: () => void;
}

function agentInitial(name: string): string {
  return (name || "?").trim().slice(0, 1).toUpperCase();
}

/** 会话时间一律按服务端时区展示，避免浏览器时区与服务端会话顺序不一致。 */
function formatSessionTime(updatedAt: string | null, timeZone: string): string {
  if (!updatedAt) return "";
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return "";
  const sameDay =
    formatServerYmd(date, timeZone) === formatServerYmd(new Date(), timeZone);
  return sameDay
    ? formatServerHourMinute(date, timeZone)
    : formatServerYmd(date, timeZone).slice(5).replace("-", "/");
}

export default function SoloConversationRail({
  agents,
  activeAgentId,
  onSelectAgent,
  sessions,
  sessionsLoading,
  activeThreadId,
  onSelectThread,
  onNewChat,
  collapsed,
  toggleDisabled = false,
  onToggleCollapsed,
}: SoloConversationRailProps) {
  const { t } = useTranslation();
  const timeZone = useServerTimezone();
  const activeAgent = agents.find((agent) => agent.agent_id === activeAgentId);

  const agentOptions = useMemo(
    () =>
      agents
        .map((agent) => ({
          value: agent.agent_id,
          label:
            agent.state === "running"
              ? agent.name
              : `${agent.name}${t("solo.agentNotRunning")}`,
        }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [agents, t],
  );

  if (collapsed) {
    return (
      <aside className={cx(styles.rail, styles.railCollapsed)}>
        <Tooltip
          title={
            toggleDisabled ? t("solo.railTooNarrow") : t("solo.expandRail")
          }
          placement="right"
        >
          <button
            type="button"
            className={styles.railIconButton}
            onClick={onToggleCollapsed}
            disabled={toggleDisabled}
            aria-label={t("solo.expandRail")}
          >
            <ChevronRight size={16} />
          </button>
        </Tooltip>
        <Tooltip title={t("solo.newChat")} placement="right">
          <button
            type="button"
            className={styles.railIconButton}
            onClick={onNewChat}
            aria-label={t("solo.newChat")}
          >
            <MessageSquarePlus size={16} />
          </button>
        </Tooltip>
        <Tooltip
          title={activeAgent?.name ?? t("solo.noAgent")}
          placement="right"
        >
          <span className={styles.railAgentAvatar}>
            {activeAgent ? agentInitial(activeAgent.name) : "?"}
          </span>
        </Tooltip>
        <Tooltip title={t("solo.sessions")} placement="right">
          <span className={styles.railCollapsedMark}>
            <MessagesSquare size={14} />
            <span>{sessions.length}</span>
          </span>
        </Tooltip>
      </aside>
    );
  }

  return (
    <aside className={styles.rail}>
      <div className={styles.railHead}>
        <div className={styles.railTitleRow}>
          <span className={styles.railTitle}>{t("solo.conversations")}</span>
          <Tooltip title={t("solo.collapseRail")}>
            <button
              type="button"
              className={styles.railIconButton}
              onClick={onToggleCollapsed}
              disabled={toggleDisabled}
              aria-label={t("solo.collapseRail")}
            >
              <ChevronLeft size={16} />
            </button>
          </Tooltip>
        </div>
        <Select
          size="small"
          className={styles.railAgentSelect}
          value={activeAgentId ?? undefined}
          placeholder={t("solo.noAgent")}
          options={agentOptions}
          onChange={onSelectAgent}
          popupMatchSelectWidth={false}
          showSearch
          optionFilterProp="label"
          notFoundContent={t("solo.noAgent")}
        />
        <button
          type="button"
          className={styles.railNewChat}
          onClick={onNewChat}
        >
          <MessageSquarePlus size={14} />
          <span>{t("solo.newChat")}</span>
        </button>
      </div>

      <div className={styles.railList}>
        {sessionsLoading && sessions.length === 0 ? (
          <div className={styles.railEmpty}>{t("solo.sessionsLoading")}</div>
        ) : sessions.length === 0 ? (
          <div className={styles.railEmpty}>{t("solo.sessionsEmpty")}</div>
        ) : (
          sessions.map((session) => (
            <button
              type="button"
              key={session.id}
              className={cx(
                styles.railSession,
                session.id === activeThreadId && styles.railSessionActive,
              )}
              onClick={() => onSelectThread(session.id)}
              title={session.name}
            >
              <span className={styles.railSessionName}>{session.name}</span>
              <span className={styles.railSessionTime}>
                {formatSessionTime(session.updatedAt, timeZone)}
              </span>
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
