import { useEffect, useMemo, useState } from "react";
import { Button, Switch } from "antd";
import {
  AlertTriangle,
  FileText,
  Hand,
  MessageSquareText,
  Puzzle,
  Radar,
  RefreshCw,
  Smartphone,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import PageShell from "../../layouts/PageShell";
import { rememberSharedElement, SharedElement } from "../../motion";
import { PluginSurfaceSlot } from "../../plugins/surfaces";
import { useIsMobile } from "../../hooks/useIsMobile";
import ActivityCore from "./ActivityCore";
import ConversationPeek from "./ConversationPeek";
import InboxPanel from "./InboxPanel";
import SessionQuickMenu from "./SessionQuickMenu";
import { useHomeActivity } from "./useHomeActivity";
import { useHomeInbox } from "./useHomeInbox";
import type { InboxItem } from "./homeInboxModel";
import type {
  HomeEvent,
  HomeEventKind,
  HomeSession,
  RingSegment,
} from "./homeActivityModel";
import styles from "./Home.module.less";

/** Live activity is a side block now; the inbox owns the main column. */
const SIDE_FEED_LIMIT = 16;
/** Local preference: keep the decorative background layer or not. */
const CORE_STORAGE_KEY = "octop.home.core";
const TONE_WINDOW_MS = 6_000;

const KIND_ICONS: Record<HomeEventKind, LucideIcon> = {
  turn: MessageSquareText,
  tool: Wrench,
  file: FileText,
  device: Smartphone,
  plugin: Puzzle,
  error: AlertTriangle,
  hitl: Hand,
};

function formatDuration(ms: number | undefined): string {
  if (!ms || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 60_000)}m`;
}

function useRelativeTime() {
  const { t } = useTranslation();
  return (at: number, now: number): string => {
    if (!at) return "";
    const seconds = Math.max(1, Math.round((now - at) / 1000));
    if (seconds < 60) return t("home.time.seconds", { count: seconds });
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return t("home.time.minutes", { count: minutes });
    const hours = Math.round(minutes / 60);
    if (hours < 24) return t("home.time.hours", { count: hours });
    return t("home.time.days", { count: Math.round(hours / 24) });
  };
}

function sessionStatusKey(session: HomeSession): "running" | "awaiting" | "idle" {
  if (session.awaitingUser) return "awaiting";
  if (session.turnActive) return "running";
  return "idle";
}

function EventRow({
  event,
  now,
  relativeTime,
}: {
  event: HomeEvent;
  now: number;
  relativeTime: (at: number, now: number) => string;
}) {
  const { t } = useTranslation();
  const Icon = KIND_ICONS[event.kind] ?? Wrench;
  const duration = formatDuration(event.durationMs);
  return (
    <li className={styles.event} data-kind={event.kind}>
      <span className={styles.eventIcon} data-kind={event.kind}>
        <Icon size={15} strokeWidth={1.8} />
      </span>
      <div className={styles.eventBody}>
        <div className={styles.eventTop}>
          <span className={styles.eventKind}>
            {t(`home.events.${event.kind}`)}
          </span>
          {event.toolName && (
            <code className={styles.eventTool}>{event.toolName}</code>
          )}
          <span
            className={styles.eventStatus}
            data-status={event.status}
          >
            {t(`home.status.${event.status}`)}
            {duration ? ` · ${duration}` : ""}
          </span>
        </div>
        {event.detail && (
          <p className={styles.eventDetail} title={event.detail}>
            {event.detail}
          </p>
        )}
        <div className={styles.eventMeta}>
          <span>{event.agentName}</span>
          <span className={styles.metaDivider}>·</span>
          <span className={styles.threadTitle}>{event.threadTitle}</span>
          <span className={styles.metaDivider}>·</span>
          <span>{relativeTime(event.at, now)}</span>
        </div>
      </div>
    </li>
  );
}

export default function HomePage() {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const {
    activity,
    sessions,
    ringSessions,
    events,
    offline,
    watchedThreads,
    ratePerMinute,
    ticks,
    links,
    sendMessage,
    cancelTurn,
    refresh,
  } = useHomeActivity();
  const inbox = useHomeInbox();
  const relativeTime = useRelativeTime();
  const now = Date.now();
  const [peekOpen, setPeekOpen] = useState(false);
  const [peekTarget, setPeekTarget] = useState<HomeSession | null>(null);
  const [menu, setMenu] = useState<{
    segment: RingSegment;
    x: number;
    y: number;
  } | null>(null);
  const [coreEnabled, setCoreEnabled] = useState(() => {
    try {
      return window.localStorage.getItem(CORE_STORAGE_KEY) !== "off";
    } catch {
      return true;
    }
  });

  const toggleCore = (next: boolean) => {
    setCoreEnabled(next);
    try {
      window.localStorage.setItem(CORE_STORAGE_KEY, next ? "on" : "off");
    } catch {
      // Storage may be unavailable in private mode; the toggle still works.
    }
  };

  const activeSessions = useMemo(
    () => sessions.filter((session) => session.turnActive || session.awaitingUser),
    [sessions],
  );
  const coreLabels = useMemo(
    () => ({
      running: t("home.sessions.running"),
      awaiting: t("home.sessions.awaiting"),
      idle: t("home.sessions.idle"),
      overflow: (count: number) => t("home.core.overflow", { count }),
      actions: {
        think: t("home.core.action.think"),
        text: t("home.core.action.text"),
        done: t("home.core.action.done"),
        error: t("home.core.action.error"),
      },
      link: {
        relay: t("home.core.link.relay"),
        summary: t("home.core.link.summary"),
        handoff: t("home.core.link.handoff"),
      },
    }),
    [t],
  );
  const visibleEvents = events.slice(0, SIDE_FEED_LIMIT);
  const hasActivity = visibleEvents.length > 0 || activeSessions.length > 0;
  /**
   * The most recent conversation, used for the landing page's primary action.
   * The home screen used to be purely observational — a decorative ring plus
   * counters — so a visitor had to find 对话 in the sidebar before doing
   * anything. "Continue" guesses their intent from real activity instead.
   */
  const latestSession = sessions[0] ?? null;
  const continueTarget = latestSession
    ? `/chat/${latestSession.agentId}/${latestSession.threadId}`
    : null;
  const openInboxThread = (item: InboxItem) => {
    if (!item.agentId || !item.threadId) return;
    navigate(`/chat/${item.agentId}/${item.threadId}`);
  };

  /** Platform + project scope of the ring, from the real agent aggregation. */
  const ringScope = useMemo(() => {
    const agents = new Set<string>();
    let threads = 0;
    for (const segment of ringSessions) {
      agents.add(segment.agentId);
      threads += Math.max(1, segment.threadIds.length);
    }
    return { agents: agents.size, threads };
  }, [ringSessions]);

  // The popover follows the newest event's thread, even if the session poll
  // has already rotated it out of the visible list.
  const focusSession = useMemo<HomeSession | null>(() => {
    const latest = events[0];
    if (latest) {
      const known = sessions.find(
        (session) =>
          session.agentId === latest.agentId &&
          session.threadId === latest.threadId,
      );
      if (known) return known;
      return {
        agentId: latest.agentId,
        agentName: latest.agentName,
        threadId: latest.threadId,
        title: latest.threadTitle,
        lastActive: latest.at,
        turnActive: latest.status === "running",
        awaitingUser: false,
      };
    }
    return sessions[0] ?? null;
  }, [events, sessions]);

  // The newest conversation that still owns an arc rotates to the slot.
  const frontThreadId = useMemo(() => {
    const keys = new Set<string>();
    for (const segment of ringSessions) {
      for (const threadId of segment.threadIds) keys.add(threadId);
    }
    for (let i = ticks.length - 1; i >= 0; i -= 1) {
      if (keys.has(ticks[i].threadId)) return ticks[i].threadId;
    }
    return focusSession?.threadId ?? null;
  }, [ringSessions, ticks, focusSession]);

  const openPeekFor = (segment: RingSegment) => {
    if (!segment.threadId) return;
    setPeekTarget({
      agentId: segment.agentId,
      agentName: segment.agentName,
      threadId: segment.threadId,
      title: segment.title,
      lastActive: 0,
      turnActive: segment.turnActive,
      awaitingUser: segment.awaitingUser,
    });
    setPeekOpen(true);
  };

  const lastTick = ticks[ticks.length - 1];
  const liveTone =
    lastTick && now - lastTick.at < TONE_WINDOW_MS ? lastTick.tone : "idle";

  useEffect(() => {
    if (!peekOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPeekOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [peekOpen]);

  const stats = [
    {
      key: "pending",
      label: t("home.stats.pending"),
      value: inbox.counts.total,
      danger: inbox.counts.total > 0,
    },
    {
      key: "pairing",
      label: t("home.stats.pairing"),
      value: inbox.counts.pairing,
      danger: false,
    },
    {
      key: "questions",
      label: t("home.stats.questions"),
      value: inbox.counts.question + inbox.counts.approval,
      danger: false,
    },
    {
      key: "tasks",
      label: t("home.stats.tasks"),
      value: inbox.counts.task,
      danger: inbox.counts.failed > 0,
    },
    {
      key: "activeTurns",
      label: t("home.stats.activeTurns"),
      value: activity?.active_turns ?? 0,
      danger: false,
    },
    {
      key: "rate",
      label: t("home.stats.rate"),
      value: ratePerMinute,
      danger: false,
    },
  ];

  return (
    <PageShell
      title={t("home.title")}
      subtitle={t("home.subtitle")}
      primaryAction={
        continueTarget ? (
          <Button
            type="primary"
            icon={<MessageSquareText size={14} strokeWidth={1.8} />}
            onClick={() => navigate(continueTarget)}
          >
            {t("home.continueSession", "继续最近会话")}
          </Button>
        ) : (
          <Button type="primary" onClick={() => navigate("/chat")}>
            {t("home.startChat", "开始对话")}
          </Button>
        )
      }
      actions={
        <div className={styles.toolbar}>
          {/* The ring is decorative chrome that only exists on wide screens;
              its toggle would be a dead control on a phone. */}
          {!isMobile && (
            <label className={styles.coreToggle}>
              <Switch
                size="small"
                checked={coreEnabled}
                onChange={toggleCore}
                aria-label={t("home.core.toggle")}
              />
              <span>{t("home.core.toggle")}</span>
            </label>
          )}
          <Button
            size="small"
            icon={<RefreshCw size={14} strokeWidth={1.8} />}
            onClick={refresh}
            aria-label={isMobile ? t("home.refresh") : undefined}
          >
            {!isMobile && t("home.refresh")}
          </Button>
        </div>
      }
    >
      <ActivityCore
        sessions={ringSessions}
        ticks={ticks}
        links={links}
        ratePerMinute={ratePerMinute}
        frontThreadId={frontThreadId}
        labels={coreLabels}
        enabled={coreEnabled}
        onSegmentContextMenu={(segment, x, y) =>
          setMenu({ segment, x, y })
        }
      />
      <div className={styles.page}>
        {(offline || inbox.offline) && (
          <div className={styles.offline} role="status">
            <AlertTriangle size={14} strokeWidth={1.8} />
            <span>{t("home.offline")}</span>
          </div>
        )}

        <div className={styles.coreLegend}>
          <span className={styles.liveBadge}>
            {t("home.core.segments", { count: ringSessions.length })}
          </span>
          {ringScope.threads > 0 && (
            <span className={styles.legendScope}>
              {t("home.core.scope", ringScope)}
            </span>
          )}
          <span className={styles.legendHint}>{t("home.core.hint")}</span>
        </div>

        <div className={styles.stats}>
          {stats.map((stat) => (
            <div key={stat.key} className={styles.stat} data-danger={stat.danger}>
              <span className={styles.statValue}>{stat.value}</span>
              <span className={styles.statLabel}>{stat.label}</span>
            </div>
          ))}
        </div>

        <div className={styles.terminal}>
          <InboxPanel
            items={inbox.items}
            counts={inbox.counts}
            loading={inbox.loading}
            error={inbox.error}
            now={now}
            relativeTime={relativeTime}
            onRefresh={inbox.refresh}
            onApprove={inbox.approvePairing}
            onReject={inbox.rejectPairing}
            onAnswer={inbox.answerQuestion}
            onAck={inbox.ackTask}
            onFollowUp={inbox.followUpTask}
            onOpenThread={openInboxThread}
          />

          <aside className={styles.side}>
            <div className={styles.sessionsBox}>
              <div className={styles.sectionHead}>
                <h2 className={styles.sectionTitle}>{t("home.feed.title")}</h2>
                <span className={styles.liveBadge} data-live={hasActivity}>
                  <span className={styles.liveDot} data-live={hasActivity} />
                  {hasActivity ? t("home.feed.live") : t("home.feed.idle")}
                </span>
              </div>
              {visibleEvents.length === 0 ? (
                <p className={styles.sessionsEmpty}>
                  {t("home.feed.emptyHint")}
                </p>
              ) : (
                <ol className={styles.feed} data-compact="true">
                  {visibleEvents.map((event) => (
                    <EventRow
                      key={event.id}
                      event={event}
                      now={now}
                      relativeTime={relativeTime}
                    />
                  ))}
                </ol>
              )}
            </div>

            <div className={styles.sessionsBox}>
              <div className={styles.sectionHead}>
                <h2 className={styles.sectionTitle}>{t("home.sessions.title")}</h2>
              </div>
              {sessions.length === 0 ? (
                <p className={styles.sessionsEmpty}>{t("home.sessions.empty")}</p>
              ) : (
                <ul className={styles.sessions}>
                  {sessions.map((session) => {
                    const status = sessionStatusKey(session);
                    return (
                      <li key={`${session.agentId}:${session.threadId}`}>
                        <button
                          type="button"
                          className={styles.session}
                          onClick={(event) => {
                            // 会话标题在聊天页标题栏有同源元素：记录位置后跳转，
                            // 由那边用共享元素接着飞过去。
                            rememberSharedElement(
                              `thread-title:${session.title}`,
                              event.currentTarget,
                            );
                            navigate(
                              `/chat/${session.agentId}/${session.threadId}`,
                            );
                          }}
                        >
                          <span
                            className={styles.sessionDot}
                            data-status={status}
                          />
                          <span className={styles.sessionBody}>
                            <SharedElement
                              as="span"
                              id={`thread-title:${session.title}`}
                              className={styles.sessionTitle}
                              title={session.title}
                            >
                              {session.title}
                            </SharedElement>
                            <span className={styles.sessionMeta}>
                              <span>{session.agentName}</span>
                              <span className={styles.metaDivider}>·</span>
                              <span>{t(`home.sessions.${status}`)}</span>
                              {session.lastActive > 0 && (
                                <>
                                  <span className={styles.metaDivider}>·</span>
                                  <span>
                                    {t("home.sessions.lastActive", {
                                      time: relativeTime(session.lastActive, now),
                                    })}
                                  </span>
                                </>
                              )}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <PluginSurfaceSlot slot="home.sidebar" />
          </aside>
        </div>

        <p className={styles.coreWatching}>
          {t("home.core.watching", { count: watchedThreads })}
        </p>
      </div>

      <button
        type="button"
        className={styles.coreTrigger}
        data-tone={liveTone}
        data-open={peekOpen}
        aria-label={t("home.core.open")}
        aria-expanded={peekOpen}
        onClick={() => {
          setPeekTarget(null);
          setPeekOpen((value) => !value);
        }}
      >
        <span className={styles.coreTriggerRing} aria-hidden="true" />
        <Radar size={15} strokeWidth={1.9} />
        <span>{t("home.core.openShort")}</span>
      </button>

      <ConversationPeek
        open={peekOpen}
        session={peekTarget ?? focusSession}
        onClose={() => setPeekOpen(false)}
      />

      <SessionQuickMenu
        segment={menu?.segment ?? null}
        anchor={menu ? { x: menu.x, y: menu.y } : null}
        onClose={() => setMenu(null)}
        onSend={sendMessage}
        onStop={cancelTurn}
        onOpenPeek={openPeekFor}
        onLocate={(segment) => {
          if (!segment.threadId) return;
          navigate(`/chat/${segment.agentId}/${segment.threadId}`);
        }}
      />
    </PageShell>
  );
}
