import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  type BaoChatMessage,
  type BaoOverview,
  type BaoTask,
  baoApi,
} from "../../api/modules/bao";
import { Mascot } from "../../components/Mascot/Mascot";
import {
  DEFAULT_MASCOT_APPEARANCE,
  syncMascotAppearance,
} from "../../components/Mascot/appearance";
import type { MascotInk, MascotShape } from "../../components/Mascot";
import { useBaoAppearance } from "../hooks/useBaoAppearance";
import { MobileChip } from "../components/MobileChip";
import { MobileComposer } from "../components/MobileComposer";
import { MobileEmpty } from "../components/MobileEmpty";
import { MobileIcon } from "../components/MobileIcon";
import { MobileSkeleton } from "../components/MobileSkeleton";
import { showMobileToast } from "../components/MobileToast";

type Tone = "ok" | "warn" | "danger" | "accent";

const TASK_TONE: Record<string, Tone> = {
  done: "ok",
  completed: "ok",
  running: "accent",
  dispatched: "accent",
  awaiting: "warn",
  pending: "warn",
  failed: "danger",
  error: "danger",
};

function formatTime(epochSeconds: number): string {
  if (!epochSeconds) return "";
  const date = new Date(epochSeconds * 1000);
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export function BaoPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { settings, name } = useBaoAppearance(true);
  const [overview, setOverview] = useState<BaoOverview | null>(null);
  const [tasks, setTasks] = useState<BaoTask[]>([]);
  const [messages, setMessages] = useState<BaoChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const taskLabels = useMemo<Record<string, string>>(
    () => ({
      done: t("mobile.bao.taskDone", "已完成"),
      completed: t("mobile.bao.taskDone", "已完成"),
      running: t("mobile.bao.taskRunning", "进行中"),
      dispatched: t("mobile.bao.taskDispatched", "已派发"),
      awaiting: t("mobile.bao.taskAwaiting", "待确认"),
      pending: t("mobile.bao.taskPending", "排队中"),
      failed: t("mobile.bao.taskFailed", "失败"),
      error: t("mobile.bao.taskFailed", "失败"),
      cancelled: t("mobile.bao.taskCancelled", "已取消"),
    }),
    [t],
  );

  const loadAll = useCallback(async () => {
    setFailed(false);
    try {
      const [nextOverview, nextTasks, history] = await Promise.all([
        baoApi.overview(10),
        baoApi.tasks(8, false),
        baoApi.chatHistory(80),
      ]);
      setOverview(nextOverview);
      setTasks(nextTasks.tasks);
      setMessages(history.messages);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    setSending(true);
    try {
      const response = await baoApi.chat({ text, scope: "global" });
      setMessages(response.messages);
      if (response.settings) {
        syncMascotAppearance({
          shape: (response.settings.shape ??
            DEFAULT_MASCOT_APPEARANCE.shape) as MascotShape,
          color: (response.settings.color ??
            DEFAULT_MASCOT_APPEARANCE.color) as MascotInk,
          bodyColor: response.settings.body_color ?? null,
          eyeColor: response.settings.eye_color ?? null,
          followTheme: response.settings.follow_theme ?? false,
        });
      }
      if (response.dispatch) {
        showMobileToast(
          t("mobile.bao.dispatched", "已派发给 {{name}}", {
            name: response.dispatch.agent_name,
          }),
        );
        setOverview(await baoApi.overview(10).catch(() => overview));
      }
      if (response.task) {
        const nextTasks = await baoApi.tasks(8, false).catch(() => null);
        if (nextTasks) setTasks(nextTasks.tasks);
      }
    } catch {
      setDraft(text);
      showMobileToast(t("mobile.bao.noReply", "宝暂时没有回应，请稍后再试"));
    } finally {
      setSending(false);
    }
  };

  const totals = overview?.totals;
  const running = totals?.running_agents ?? 0;
  const awaiting = totals?.awaiting_user ?? 0;
  const statusText = settings?.proactive_muted
    ? t("mobile.bao.muted", "免打扰已开启")
    : awaiting > 0
    ? t("mobile.bao.awaitingTasks", "{{n}} 项任务等待你确认", { n: awaiting })
    : running > 0
    ? t("mobile.bao.runningAgents", "{{n}} 位专家正在处理", { n: running })
    : t("mobile.bao.standby", "随时待命");

  return (
    <div className="m-chat">
      <header className="m-chat-head">
        <span style={{ width: 8 }} />
        <div className="m-chat-head-main">
          <div className="m-chat-head-name">{name}</div>
          <div className="m-chat-head-sub">{statusText}</div>
        </div>
        <button
          type="button"
          className="m-iconbtn"
          aria-label={t("common.refresh", "刷新")}
          onClick={() => void loadAll()}
        >
          <MobileIcon name="refresh" />
        </button>
      </header>

      <div className="m-chat-scroll" ref={scrollRef}>
        <div className="m-bao-hero">
          <div className="m-bao-halo">
            <Mascot size={112} label={name} />
          </div>
          <div className="m-bao-name">{name}</div>
          <div className="m-bao-status">{statusText}</div>
        </div>

        {loading ? (
          <MobileSkeleton rows={2} />
        ) : failed && !overview ? (
          <MobileEmpty
            icon="alert"
            title={t("mobile.bao.unreachableTitle", "宝暂时联系不上")}
            description={t(
              "mobile.bao.unreachableDesc",
              "检查后端服务后重试。",
            )}
            action={
              <button
                type="button"
                className="m-btn m-btn--primary"
                onClick={() => void loadAll()}
              >
                {t("common.retry", "重试")}
              </button>
            }
          />
        ) : (
          <>
            <div className="m-stats m-mt16">
              <div className="m-stat">
                <div className="m-stat-value">{totals?.projects ?? 0}</div>
                <div className="m-stat-label">
                  {t("mobile.bao.projects", "项目")}
                </div>
              </div>
              <div className="m-stat">
                <div className="m-stat-value">{running}</div>
                <div className="m-stat-label">
                  {t("mobile.bao.inProgress", "处理中")}
                </div>
              </div>
              <div className="m-stat">
                <div className="m-stat-value">{awaiting}</div>
                <div className="m-stat-label">
                  {t("mobile.bao.awaiting", "待确认")}
                </div>
              </div>
            </div>

            {tasks.length > 0 ? (
              <div className="m-section">
                <div className="m-section-head">
                  <div className="m-section-title">
                    {t("mobile.bao.recentTasks", "最近任务")}
                  </div>
                  <span className="m-section-more">
                    {t("mobile.bao.taskCount", "{{n}} 条", { n: tasks.length })}
                  </span>
                </div>
                <div className="m-task-strip">
                  {tasks.map((task) => (
                    <button
                      type="button"
                      key={task.id}
                      className="m-task-mini"
                      onClick={() =>
                        navigate(`/m/chat/${task.agent_id}/${task.thread_id}`)
                      }
                    >
                      <div className="m-task-mini-title">{task.task_text}</div>
                      <div className="m-task-mini-meta">
                        <MobileChip tone={TASK_TONE[task.status] ?? "default"}>
                          {taskLabels[task.status] ?? task.status}
                        </MobileChip>
                        <span className="m-truncate">{task.agent_name}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="m-section">
              <div className="m-section-head">
                <div className="m-section-title">
                  {t("mobile.bao.chatWith", "和{{name}}聊聊", { name })}
                </div>
              </div>
              {messages.length === 0 ? (
                <MobileEmpty
                  icon="bao"
                  title={t("mobile.bao.noChatTitle", "还没有对话")}
                  description={t(
                    "mobile.bao.noChatDesc",
                    "可以让宝派发任务、汇总进展，或聊聊今天的安排。",
                  )}
                />
              ) : (
                <div className="m-bao-chat">
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className={
                        message.role === "user"
                          ? "m-bao-msg m-bao-msg--user"
                          : "m-bao-msg m-bao-msg--bao"
                      }
                    >
                      {message.text}
                      <div
                        className="m-hint"
                        style={{ marginTop: 4, opacity: 0.7 }}
                      >
                        {formatTime(message.created_at)}
                      </div>
                    </div>
                  ))}
                  {sending ? (
                    <div className="m-chat-status">
                      <span className="m-spin" />
                      {t("mobile.bao.thinking", "{{name}}正在整理…", { name })}
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      <MobileComposer
        value={draft}
        onChange={setDraft}
        onSend={() => void send()}
        placeholder={t(
          "mobile.bao.composerPlaceholder",
          "和{{name}}说点什么…",
          {
            name,
          },
        )}
        disabled={sending}
        hint={sending ? t("mobile.bao.waitingReply", "等待宝回应…") : undefined}
      />
    </div>
  );
}
