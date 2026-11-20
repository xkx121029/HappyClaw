import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  Button,
  Checkbox,
  Input,
  Select,
  Spin,
  Switch,
  Tag,
} from "antd";
import type { TFunction } from "i18next";
import { Pencil, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  type BaoChatMessage,
  type BaoProject,
  type BaoRouteDecision,
} from "../../api/modules/bao";
import { ApiHttpError } from "../../api/request";
import { useBao } from "./BaoContext";
import { findProject, type BaoScope } from "./baoModel";
import type { BaoTaskRecord } from "./baoTaskStore";
import { useBaoChat, useBaoOverview } from "./useBaoData";
import { Mascot, mascotStatusInk } from "../Mascot";
import { useIsMobile } from "../../hooks/useIsMobile";
import styles from "./Bao.module.less";

const NEW_SESSION = "__new__";

interface ManualTarget {
  projectKey: string | null;
  agentId: string | null;
  threadId: string;
}

const EMPTY_TARGET: ManualTarget = {
  projectKey: null,
  agentId: null,
  threadId: NEW_SESSION,
};

function projectLabel(project: BaoProject, fallback: string): string {
  return project.name || fallback;
}

function formatTime(seconds: number, locale: string): string {
  try {
    return new Intl.DateTimeFormat(locale, {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(seconds * 1000));
  } catch {
    return "";
  }
}

/** Team members have no runtime of their own: the picker must not offer them. */
function agentOptionLabel(
  agent: BaoProject["agents"][number],
  t: TFunction,
): string {
  if (agent.direct_dispatchable === false) {
    return `${agent.name} · ${t("bao.dispatch.teamMemberShort", "团队成员")}`;
  }
  return agent.model_ready
    ? agent.name
    : `${agent.name} · ${t("bao.projects.noModel")}`;
}

function agentOptionDisabled(agent: BaoProject["agents"][number]): boolean {
  return !agent.model_ready || agent.direct_dispatchable === false;
}

/**
 * Bao is a page, not a chat with a worker: each turn is a dispatch the Router
 * decided, with the decision, reason, live follow-up and aggregated result.
 *
 * The transcript itself is Bao's conversation memory, persisted server-side, so
 * references like "also do that one" survive a reload.
 */
export default function BaoPage() {
  const { t, i18n } = useTranslation();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { overview, loading, error, reload } = useBaoOverview(true);
  const { messages, send: sendChat } = useBaoChat(true);
  const {
    tasks,
    refreshTasks,
    name,
    appearance: baoLook,
    openNaming,
    muted,
    setMuted,
  } = useBao();

  // The URL is the only scope authority: /bao is the global Bao, while
  // /bao?project=… is that one project's Bao. There is deliberately no
  // in-page switch — cross-project work belongs to the global entry.
  const projectParam = searchParams.get("project") || null;
  const scope: BaoScope = projectParam ? "project" : "global";
  const projectKey = projectParam;

  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [manual, setManual] = useState<ManualTarget>(EMPTY_TARGET);
  const [ask, setAsk] = useState<{
    text: string;
    decision: BaoRouteDecision;
  } | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const focus = () => composerRef.current?.focus();
    window.addEventListener("octop:bao:focus-composer", focus);
    return () => window.removeEventListener("octop:bao:focus-composer", focus);
  }, []);

  const activeProject = findProject(overview, projectKey);
  // A project route that names an unknown project stays on that route and says
  // so; it must never silently slide into a different project.
  const projectMissing =
    scope === "project" && !!overview && !loading && !activeProject;
  const scopedProjects = useMemo(() => {
    if (!overview) return [];
    if (scope === "project") return activeProject ? [activeProject] : [];
    return overview.projects;
  }, [activeProject, overview, scope]);

  const projectOptions = useMemo(
    () =>
      scopedProjects.map((project) => ({
        value: project.key,
        label: projectLabel(project, t("bao.projects.defaultName")),
      })),
    [scopedProjects, t],
  );

  const manualProject = findProject(overview, manual.projectKey) ?? null;
  const manualAgents = manualProject?.agents ?? [];
  const manualSessions =
    manualProject?.sessions.filter(
      (session) => session.agent_id === manual.agentId,
    ) ?? [];

  const pickProject = (key: string | null) => {
    setManual({ projectKey: key, agentId: null, threadId: NEW_SESSION });
  };

  const pickAgent = (agentId: string | null) => {
    setManual((prev) => ({ ...prev, agentId, threadId: NEW_SESSION }));
  };

  const send = async (
    valueOverride?: string,
    targetOverride?: ManualTarget | null,
  ) => {
    const value = (valueOverride ?? text).trim();
    if (!value || submitting) return;
    if (scope === "project" && !activeProject) {
      setSendError(
        t("bao.scope.unknownProject", { project: projectKey ?? "" }),
      );
      return;
    }
    const target =
      targetOverride === undefined ? (manualOpen ? manual : null) : targetOverride;
    if (target && !target.agentId) {
      setSendError(t("bao.dispatch.noAgent"));
      return;
    }
    setSubmitting(true);
    setSendError(null);
    try {
      const response = await sendChat({
        text: value,
        scope,
        project_key: scope === "project" ? projectKey : null,
        ...(target?.agentId
          ? {
              agent_id: target.agentId,
              thread_id:
                target.threadId === NEW_SESSION ? null : target.threadId,
            }
          : {}),
      });

      if (response.needs_target) {
        const decision: BaoRouteDecision = response.decision ?? {
          decided: false,
          needs_target: true,
          reason: {
            code:
              response.reply_code === "team_member"
                ? "team_member"
                : "ambiguous_project",
            params: response.reply_params,
          },
          candidates: response.candidates,
        };
        setAsk({ text: value, decision });
        const firstProject =
          scope === "project"
            ? activeProject
            : (findProject(
                overview,
                decision.candidates?.projects[0]?.key ?? null,
              ) ??
              scopedProjects[0] ??
              null);
        const firstAgent =
          decision.candidates?.agents.find(
            (agent) =>
              agent.project_key === firstProject?.key &&
              agent.direct_dispatchable !== false,
          )?.agent_id ??
          firstProject?.agents.find((agent) => agent.direct_dispatchable !== false)
            ?.agent_id ??
          null;
        setManual({
          projectKey: firstProject?.key ?? null,
          agentId: firstAgent,
          threadId: NEW_SESSION,
        });
        setText("");
        setManualOpen(false);
        return;
      }

      setText("");
      setAsk(null);
      if (target) {
        setManual(EMPTY_TARGET);
        setManualOpen(false);
      }
      await refreshTasks();
      void reload(true);
    } catch (err) {
      setSendError(dispatchErrorMessage(err, t));
    } finally {
      setSubmitting(false);
    }
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      void send();
    }
  };

  const feed = useMemo(
    () => [...tasks].sort((a, b) => a.dispatchedAt - b.dispatchedAt),
    [tasks],
  );

  const taskById = useMemo(
    () => new Map(tasks.map((task) => [task.id, task])),
    [tasks],
  );

  // Tasks created through chat carry their id on Bao's reply; everything else
  // (legacy imports, manual dispatch) still gets a standalone card.
  const referencedTaskIds = useMemo(() => {
    const ids = new Set<string>();
    for (const message of messages) {
      if (message.role === "bao" && message.task_id) ids.add(message.task_id);
    }
    return ids;
  }, [messages]);

  const orphanTasks = useMemo(
    () => feed.filter((task) => !referencedTaskIds.has(task.id)),
    [feed, referencedTaskIds],
  );

  // "working" while Bao has live dispatches; otherwise the neutral idle pose.
  const hasLiveTask = tasks.some(
    (task) => task.status === "running" || task.status === "awaiting",
  );

  const projectScopeLabel = activeProject
    ? projectLabel(activeProject, t("bao.projects.defaultName"))
    : (projectKey ?? t("bao.projects.defaultName"));

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <h1 className={styles.title}>
            <Mascot
              size={26}
              {...baoLook}
              color={mascotStatusInk(baoLook, hasLiveTask ? "working" : null)}
              state={hasLiveTask ? "working" : "idle"}
              className={styles.titleGlyph}
              surface="var(--fn-bg-base)"
            />
            {name}
          </h1>
          <Button
            type="text"
            size="small"
            className={styles.renameName}
            onClick={openNaming}
            aria-label={t("bao.identity.rename", "改名")}
            title={t("bao.identity.rename", "改名")}
          >
            <Pencil size={13} />
          </Button>
          <Tag color="blue" bordered={false} className={styles.routerBadge}>
            {t("bao.page.routerBadge")}
          </Tag>
          <div className={styles.headerTools}>
            <span className={styles.muteLabel}>
              {t("bao.settings.mute", "静音推送")}
            </span>
            <Switch
              size="small"
              checked={muted}
              onChange={(checked) => void setMuted(checked)}
              aria-label={t("bao.settings.mute", "静音推送")}
            />
            <Tag
              bordered={false}
              color={scope === "project" ? "geekblue" : "blue"}
            >
              {scope === "project"
                ? t("bao.scope.project")
                : t("bao.scope.global")}
            </Tag>
            <Button
              type="text"
              onClick={() => void reload()}
              loading={loading}
              aria-label={isMobile ? t("bao.refresh") : undefined}
            >
              {isMobile ? <RefreshCw size={16} strokeWidth={1.8} /> : t("bao.refresh")}
            </Button>
          </div>
        </div>
        <p className={styles.subtitle}>
          {scope === "project"
            ? t("bao.page.scopeProject", { project: projectScopeLabel })
            : t("bao.scope.hint.global")}
        </p>
      </header>

      <main className={styles.transcript} aria-live="polite">
        <div className={styles.transcriptInner}>
          {!projectMissing && messages.length === 0 && feed.length === 0 ? (
            <section className={styles.welcome}>
              <h2 className={styles.welcomeTitle}>
                {t("bao.page.emptyTitle")}
              </h2>
              <p>{t("bao.page.boundary")}</p>
              <ul className={styles.welcomeList}>
                <li>{t("bao.page.capability.sessions")}</li>
                <li>{t("bao.page.capability.newSession")}</li>
                <li>{t("bao.page.capability.followUp")}</li>
              </ul>
              <p className={styles.welcomeHint}>{t("bao.tasks.retryHint")}</p>
            </section>
          ) : null}

          {projectMissing ? (
            <section className={styles.welcome}>
              <p className={styles.errorText}>
                {t("bao.scope.unknownProject", { project: projectKey ?? "" })}
              </p>
              <Button size="small" onClick={() => navigate("/bao")}>
                {t("bao.entry.open")}
              </Button>
            </section>
          ) : null}

          {error && !overview ? (
            <section className={styles.welcome}>
              <p className={styles.errorText}>
                {t("bao.error", { message: error.message })}
              </p>
              <Button size="small" onClick={() => void reload()}>
                {t("bao.retry")}
              </Button>
            </section>
          ) : null}

          {!overview && loading ? (
            <div className={styles.loadingBlock}>
              <Spin size="small" /> <span>{t("bao.loading")}</span>
            </div>
          ) : null}

          {messages.map((message) => (
            <MessageTurn
              key={message.id}
              message={message}
              task={message.task_id ? taskById.get(message.task_id) : undefined}
              locale={i18n.language}
              onOpen={(task) =>
                navigate(`/chat/${task.agentId}/${task.threadId}`)
              }
              onFollowUp={() => void refreshTasks()}
            />
          ))}

          {orphanTasks.map((task) => (
            <article key={task.id} className={styles.turn}>
              <div className={styles.userBubble}>{task.text}</div>
              <TaskCard
                task={task}
                locale={i18n.language}
                onOpen={() =>
                  navigate(`/chat/${task.agentId}/${task.threadId}`)
                }
                onFollowUp={() => void refreshTasks()}
              />
            </article>
          ))}

          {ask ? (
            <section className={styles.askCard}>
              <div className={styles.askTitle}>
                {t("bao.route.ask.title")}
              </div>
              <p className={styles.reason}>
                {askReasonText(ask.decision, t)}
              </p>
              {ask.decision.model_attempt?.tried ? (
                <p className={styles.reason}>
                  {t("bao.route.model.attempted", {
                    reason: modelAttemptText(ask.decision.model_attempt.code, t),
                  })}
                </p>
              ) : null}
              <div className={styles.askActions}>
                {scope === "project" ? (
                  <Tag title={t("bao.scope.hint.project")}>
                    {projectScopeLabel}
                  </Tag>
                ) : (
                  <Select
                    value={manual.projectKey ?? undefined}
                    placeholder={t("bao.composer.project")}
                    options={projectOptions}
                    style={{ minWidth: 180 }}
                    onChange={(value: string) => pickProject(value)}
                  />
                )}
                <Select
                  value={manual.agentId ?? undefined}
                  placeholder={t("bao.composer.agent")}
                  options={manualAgents.map((agent) => ({
                    value: agent.agent_id,
                    label: agentOptionLabel(agent, t),
                    disabled: agentOptionDisabled(agent),
                  }))}
                  style={{ minWidth: 180 }}
                  onChange={(value: string) => pickAgent(value)}
                />
                <Select
                  value={manual.threadId}
                  options={[
                    {
                      value: NEW_SESSION,
                      label: t("bao.composer.newSession"),
                    },
                    ...manualSessions.map((session) => ({
                      value: session.thread_id,
                      label:
                        session.title || t("bao.sessions.untitled"),
                    })),
                  ]}
                  style={{ minWidth: 200 }}
                  onChange={(value: string) =>
                    setManual((prev) => ({ ...prev, threadId: value }))
                  }
                />
                <Button
                  type="primary"
                  onClick={() => {
                    const pending = ask;
                    setAsk(null);
                    void send(pending.text, manual);
                  }}
                  disabled={!manual.agentId || !manualProject}
                >
                  {t("bao.route.ask.confirm")}
                </Button>
                <Button onClick={() => setAsk(null)}>
                  {t("bao.route.ask.cancel")}
                </Button>
              </div>
              {ask.decision.reason.code === "no_agent" ? (
                <Button type="link" size="small" onClick={() => navigate("/experts")}>
                  {t("bao.projects.emptyAction")}
                </Button>
              ) : null}
            </section>
          ) : null}
        </div>
      </main>

      <footer className={styles.composer}>
        <div className={styles.composerInner}>
          <Input.TextArea
            ref={composerRef}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onComposerKeyDown}
            placeholder={
              isMobile
                ? t(
                    "bao.composer.placeholderMobile",
                    "告诉宝要做什么，它会选择项目、专家和会话并持续跟进。",
                  )
                : t("bao.composer.placeholder")
            }
            autoSize={{ minRows: 2, maxRows: 6 }}
            aria-label={t("bao.composer.placeholder")}
          />
          <div className={styles.composerBar}>
            <Checkbox
              checked={manualOpen}
              onChange={(event) => {
                setManualOpen(event.target.checked);
                if (event.target.checked && !manual.projectKey) {
                  const key = projectKey ?? scopedProjects[0]?.key ?? null;
                  const project = findProject(overview, key);
                  setManual({
                    projectKey: key,
                    agentId:
                      project?.agents.find(
                        (agent) => agent.direct_dispatchable !== false,
                      )?.agent_id ?? null,
                    threadId: NEW_SESSION,
                  });
                }
              }}
            >
              {t("bao.composer.specify")}
            </Checkbox>
            {manualOpen ? (
              <>
                {scope === "project" ? (
                  <Tag title={t("bao.scope.hint.project")}>
                    {projectScopeLabel}
                  </Tag>
                ) : (
                  <Select
                    size="small"
                    value={manual.projectKey ?? undefined}
                    placeholder={t("bao.composer.project")}
                    options={projectOptions}
                    style={{ minWidth: 150 }}
                    onChange={(value: string) => pickProject(value)}
                  />
                )}
                <Select
                  size="small"
                  value={manual.agentId ?? undefined}
                  placeholder={t("bao.composer.agent")}
                  options={manualAgents.map((agent) => ({
                    value: agent.agent_id,
                    label: agentOptionLabel(agent, t),
                    disabled: agentOptionDisabled(agent),
                  }))}
                  style={{ minWidth: 150 }}
                  onChange={(value: string) => pickAgent(value)}
                />
                <Select
                  size="small"
                  value={manual.threadId}
                  options={[
                    {
                      value: NEW_SESSION,
                      label: t("bao.composer.newSession"),
                    },
                    ...manualSessions.map((session) => ({
                      value: session.thread_id,
                      label: session.title || t("bao.sessions.untitled"),
                    })),
                  ]}
                  style={{ minWidth: 170 }}
                  onChange={(value: string) =>
                    setManual((prev) => ({ ...prev, threadId: value }))
                  }
                />
              </>
            ) : null}
            <span className={styles.composerHint}>{t("bao.composer.hint")}</span>
            <span className={styles.composerSpacer} />
            <Button
              type="primary"
              loading={submitting}
              disabled={!text.trim() || projectMissing}
              onClick={() => void send()}
            >
              {submitting ? t("bao.composer.sending") : t("bao.composer.send")}
            </Button>
          </div>
          {sendError ? (
            <div className={styles.errorRow}>
              <Mascot
                size={18}
                {...baoLook}
                color={mascotStatusInk(baoLook, "error")}
                state="sad"
                surface="var(--fn-bg-base)"
              />
              <p className={styles.errorText}>{sendError}</p>
            </div>
          ) : null}
        </div>
      </footer>
    </div>
  );
}

interface MessageTurnProps {
  message: BaoChatMessage;
  task?: BaoTaskRecord;
  locale: string;
  onOpen: (task: BaoTaskRecord) => void;
  onFollowUp: () => void;
}

function MessageTurn({
  message,
  task,
  locale,
  onOpen,
  onFollowUp,
}: MessageTurnProps) {
  const { appearance: baoLook } = useBao();
  if (message.role === "user") {
    return (
      <div className={styles.turn}>
        <div className={styles.userBubble}>{message.text}</div>
      </div>
    );
  }
  return (
    <div className={styles.turn}>
      <div className={styles.baoBubbleRow}>
        <Mascot
          size={22}
          {...baoLook}
          state={task?.status === "failed" ? "sad" : "idle"}
          className={styles.baoBubbleGlyph}
          surface="var(--fn-bg-base)"
        />
        <div className={styles.baoBubble}>{message.text}</div>
      </div>
      {task ? (
        <TaskCard
          task={task}
          locale={locale}
          onOpen={() => onOpen(task)}
          onFollowUp={onFollowUp}
        />
      ) : null}
    </div>
  );
}

interface TaskCardProps {
  task: BaoTaskRecord;
  locale: string;
  onOpen: () => void;
  onFollowUp: () => void;
}

function TaskCard({ task, locale, onOpen, onFollowUp }: TaskCardProps) {
  const { t } = useTranslation();
  const { appearance: baoLook } = useBao();
  const pending = task.status === "running" || task.status === "awaiting";
  const steps = taskSteps(task);
  // The same mascot follows the dispatch through its real stages.
  const glyphState =
    task.status === "failed"
      ? "sad"
      : task.status === "done"
        ? "happy"
        : task.status === "awaiting"
          ? "listening"
          : "working";
  const glyphColor = mascotStatusInk(baoLook, pending ? "working" : null);
  return (
    <div className={styles.baoCard}>
      <div className={styles.decisionRow}>
        <Mascot
          size={20}
          {...baoLook}
          color={glyphColor}
          state={glyphState}
          className={styles.decisionGlyph}
          surface="var(--fn-bg-base)"
        />
        <span>{t("bao.route.to")}</span>
        <span className={styles.targetChip}>{task.projectName}</span>
        <span className={styles.arrow}>/</span>
        <span className={styles.targetChip}>{task.agentName}</span>
        <span className={styles.arrow}>/</span>
        <span className={styles.targetChip}>
          {task.created
            ? t("bao.turn.created")
            : task.sessionTitle || t("bao.sessions.untitled")}
        </span>
      </div>
      <div className={styles.reason}>
        {t("bao.route.from")}：{reasonText(task.routeReason, t)}
      </div>
      <div className={styles.statusRow}>
        {steps.map((step) => (
          <span
            key={step.key}
            className={`${styles.step} ${
              step.state === "done"
                ? styles.stepDone
                : step.state === "active"
                  ? styles.stepActive
                  : ""
            }`}
          >
            <span className={styles.stepDot} aria-hidden />
            {t(`bao.turn.${step.key}`)}
          </span>
        ))}
        <span className={styles.arrow}>·</span>
        <span>{t(`bao.tasks.status.${task.status}`)}</span>
        {(task.followupCount ?? 0) > 0 ? (
          <>
            <span className={styles.arrow}>·</span>
            <span>
              {t("bao.turn.followupCount", {
                count: task.followupCount,
              })}
            </span>
          </>
        ) : null}
      </div>
      {task.status === "done" ? (
        <div className={styles.result}>
          {t("bao.turn.result")}：{task.resultText || t("bao.tasks.noResult")}
        </div>
      ) : null}
      {task.status === "failed" ? (
        <div className={`${styles.result} ${styles.resultError}`}>
          {t("bao.turn.error")}：
          {task.errorText || t("bao.tasks.errorUnknown")}
        </div>
      ) : null}
      <div className={styles.cardActions}>
        <span>{t("bao.turn.dispatchedAt", { time: formatTime(task.dispatchedAt, locale) })}</span>
        {pending ? (
          <>
            <span>·</span>
            <span>{t("bao.turn.following")}</span>
            <Button type="link" size="small" onClick={onFollowUp}>
              {t("bao.tasks.refreshNow")}
            </Button>
          </>
        ) : (
          <>
            <span>·</span>
            <span>{t("bao.turn.followed")}</span>
          </>
        )}
        <span className={styles.composerSpacer} />
        <Button type="link" size="small" onClick={onOpen}>
          {t("bao.turn.jump")}
        </Button>
      </div>
    </div>
  );
}

function taskSteps(task: BaoTaskRecord): Array<{
  key: string;
  state: "done" | "active" | "pending";
}> {
  if (task.status === "failed") {
    return [
      { key: "stepDispatched", state: "done" },
      { key: "stepFailed", state: "active" },
    ];
  }
  if (task.status === "done") {
    return [
      { key: "stepDispatched", state: "done" },
      { key: "stepRunning", state: "done" },
      { key: "stepDone", state: "done" },
    ];
  }
  if (task.status === "awaiting") {
    return [
      { key: "stepDispatched", state: "done" },
      { key: "stepRunning", state: "done" },
      { key: "stepAwaiting", state: "active" },
    ];
  }
  return [
    { key: "stepDispatched", state: "done" },
    { key: "stepRunning", state: "active" },
  ];
}

const REASON_KEYS: Record<string, string> = {
  session_title: "bao.route.reason.sessionTitle",
  agent_name: "bao.route.reason.agentName",
  agent_name_new_thread: "bao.route.reason.agentNameNewThread",
  project_name_active_session: "bao.route.reason.projectActiveSession",
  project_name_recent_session: "bao.route.reason.projectRecentSession",
  scope_active_session: "bao.route.reason.scopeActiveSession",
  scope_recent_session: "bao.route.reason.scopeRecentSession",
  new_thread: "bao.route.reason.newThread",
  manual_target: "bao.route.reason.manual",
  model_route: "bao.route.reason.modelRoute",
  also: "bao.route.reason.also",
  retry: "bao.route.reason.retry",
  team_member: "bao.route.reason.teamMember",
};

const MODEL_ATTEMPT_KEYS: Record<string, string> = {
  model_failed: "bao.route.model.failed",
  model_unsure: "bao.route.model.unsure",
  model_unavailable: "bao.route.model.unavailable",
  no_candidates: "bao.route.model.noCandidates",
};

function modelAttemptText(code: string, t: TFunction): string {
  return t(MODEL_ATTEMPT_KEYS[code] ?? "bao.route.model.failed");
}

function reasonText(
  reason: { code: string; params: Record<string, string | number> } | undefined,
  t: TFunction,
): string {
  if (!reason) return t("bao.route.reason.generic");
  const key = REASON_KEYS[reason.code] ?? "bao.route.reason.generic";
  return t(key, reason.params);
}

function askReasonText(
  decision: BaoRouteDecision,
  t: TFunction,
): string {
  switch (decision.reason.code) {
    case "team_member":
      return t("bao.route.ask.teamMember", {
        agent: decision.reason.params.agent ?? "",
        team: decision.reason.params.team ?? "",
      });
    case "ambiguous_project":
      return t("bao.route.ask.ambiguousProject");
    case "no_agent":
      return t("bao.route.ask.noAgent");
    case "no_project":
      return t("bao.route.ask.noProject");
    default:
      return t("bao.route.ask.ambiguousProject");
  }
}

function dispatchErrorMessage(err: unknown, t: TFunction): string {
  if (err instanceof ApiHttpError) {
    if (err.code === "THREAD_TURN_ACTIVE") return t("bao.dispatch.busy");
    if (err.code === "AGENT_NO_MODEL") return t("bao.dispatch.noModel");
    if (err.code === "AGENT_NOT_RUNNING") return t("bao.dispatch.notRunning");
    if (err.code === "TEAM_MEMBER_NOT_DIRECT") return t("bao.dispatch.teamMember");
    if (err.status >= 500) return t("bao.dispatch.serverError");
  }
  return t("bao.dispatch.failed", {
    message: err instanceof Error ? err.message : String(err),
  });
}
