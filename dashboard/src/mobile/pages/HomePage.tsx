import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { octopCronApi } from "../../api/modules/cronjob";
import {
  octopThreadsApi,
  type OctopThread,
} from "../../api/modules/octopThreads";
import type { OctopCronRow } from "../../api/types";
import { useAgent } from "../../context/AgentContext";
import { MobileAvatar } from "../components/MobileAvatar";
import { MobileCard } from "../components/MobileCard";
import { MobileChip, MobileDot } from "../components/MobileChip";
import { MobileEmpty } from "../components/MobileEmpty";
import { MobileIcon, type MobileIconName } from "../components/MobileIcon";
import { MobilePage } from "../components/MobilePage";
import { MobileSheet } from "../components/MobileSheet";
import { MobileSkeleton } from "../components/MobileSkeleton";

export function HomePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const greeting = useCallback((): string => {
    const hour = new Date().getHours();
    if (hour < 6) return t("mobile.home.greetingNight", "夜深了");
    if (hour < 12) return t("mobile.home.greetingMorning", "早上好");
    if (hour < 14) return t("mobile.home.greetingNoon", "中午好");
    if (hour < 18) return t("mobile.home.greetingAfternoon", "下午好");
    return t("mobile.home.greetingEvening", "晚上好");
  }, [t]);

  const relativeTime = useCallback(
    (epochSeconds: number): string => {
      if (!epochSeconds) return "";
      const diff = Date.now() - epochSeconds * 1000;
      if (diff < 60_000) return t("mobile.time.justNow", "刚刚");
      if (diff < 3_600_000) {
        return t("mobile.time.minutesAgo", "{{n}} 分钟前", {
          n: Math.floor(diff / 60_000),
        });
      }
      if (diff < 86_400_000) {
        return t("mobile.time.hoursAgo", "{{n}} 小时前", {
          n: Math.floor(diff / 3_600_000),
        });
      }
      const date = new Date(epochSeconds * 1000);
      return `${date.getMonth() + 1}/${date.getDate()}`;
    },
    [t],
  );

  const shortcuts: Array<{
    label: string;
    sub: string;
    icon: MobileIconName;
    path: string;
  }> = [
    {
      label: t("mobile.nav.experts", "专家"),
      sub: t("mobile.home.shortcutExpertsSub", "切换与启动"),
      icon: "experts",
      path: "/m/experts",
    },
    {
      label: t("mobile.nav.tasks", "任务"),
      sub: t("mobile.home.shortcutTasksSub", "定时与运行"),
      icon: "clock",
      path: "/m/tasks",
    },
    {
      label: t("mobile.nav.knowledgeBases", "知识库"),
      sub: t("mobile.home.shortcutKnowledgeSub", "资料与文档"),
      icon: "book",
      path: "/m/knowledge-bases",
    },
    {
      label: t("mobile.nav.connectors", "连接器"),
      sub: t("mobile.home.shortcutConnectorsSub", "工具与插件"),
      icon: "plug",
      path: "/m/connectors",
    },
  ];

  const {
    agents,
    activeAgent,
    activeAgentId,
    setActiveAgent,
    loading,
    refresh,
  } = useAgent();
  const [threads, setThreads] = useState<OctopThread[]>([]);
  const [tasks, setTasks] = useState<OctopCronRow[]>([]);
  const [fetching, setFetching] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [agentSheet, setAgentSheet] = useState(false);

  const load = useCallback(async () => {
    if (!activeAgentId) {
      setThreads([]);
      setTasks([]);
      setFetching(false);
      return;
    }
    try {
      const [rows, cron] = await Promise.all([
        octopThreadsApi.list(activeAgentId, 8),
        octopCronApi.list(activeAgentId).catch(() => [] as OctopCronRow[]),
      ]);
      setThreads(rows);
      setTasks(cron);
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setFetching(false);
    }
  }, [activeAgentId]);

  useEffect(() => {
    setFetching(true);
    void load();
  }, [load]);

  const refreshAll = async () => {
    setRefreshing(true);
    await Promise.all([refresh({ silent: true }), load()]);
    setRefreshing(false);
  };

  const enabledTasks = tasks.filter((task) => task.enabled).length;
  const recent = threads.slice(0, 6);

  return (
    <MobilePage>
      <div className="m-hero">
        <div className="m-eyebrow">HAPPYCLAW</div>
        <div className="m-hero-greet">
          {greeting()}，{activeAgent?.name ?? t("mobile.home.friend", "朋友")}
        </div>
        <div className="m-hero-sub">
          {activeAgent?.description ||
            t("mobile.home.heroFallback", "今天想聊点什么？")}
        </div>
        <div className="m-rowflex m-mt16">
          <button
            type="button"
            className="m-chip m-chip--accent"
            onClick={() => setAgentSheet(true)}
            style={{ height: 30, paddingRight: 8 }}
          >
            <MobileAvatar
              name={activeAgent?.name ?? "?"}
              src={activeAgent?.icon_url}
              color={activeAgent?.color}
              size={18}
            />
            {activeAgent?.name ?? t("mobile.home.chooseExpert", "选择专家")}
            <MobileIcon
              name="chevron"
              size={13}
              style={{ transform: "rotate(90deg)" }}
            />
          </button>
          <span className="m-grow" />
          <button
            type="button"
            className="m-iconbtn"
            aria-label={t("common.refresh", "刷新")}
            onClick={() => void refreshAll()}
          >
            <MobileIcon
              name="refresh"
              size={19}
              style={
                refreshing
                  ? { animation: "m-rotate .8s linear infinite" }
                  : undefined
              }
            />
          </button>
        </div>
      </div>

      <div className="m-section">
        <div className="m-stats">
          <button
            type="button"
            className="m-stat"
            onClick={() => navigate("/m/chat")}
          >
            <div className="m-stat-value">{threads.length}</div>
            <div className="m-stat-label">
              {t("mobile.home.statRecentChats", "最近对话")}
            </div>
          </button>
          <button
            type="button"
            className="m-stat"
            onClick={() => navigate("/m/tasks")}
          >
            <div className="m-stat-value">{enabledTasks}</div>
            <div className="m-stat-label">
              {t("mobile.home.statEnabledTasks", "启用任务")}
            </div>
          </button>
          <button
            type="button"
            className="m-stat"
            onClick={() => navigate("/m/experts")}
          >
            <div className="m-stat-value">{agents.length}</div>
            <div className="m-stat-label">
              {t("mobile.home.statAvailableExperts", "可用专家")}
            </div>
          </button>
        </div>
      </div>

      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.home.shortcuts", "快捷入口")}
          </div>
        </div>
        <div className="m-grid2">
          {shortcuts.map((item) => (
            <button
              type="button"
              key={item.path}
              className="m-quicklink"
              onClick={() => navigate(item.path)}
            >
              <span className="m-row-icon">
                <MobileIcon name={item.icon} size={19} />
              </span>
              <span>
                <span className="m-quicklink-label">{item.label}</span>
                <span
                  className="m-quicklink-sub"
                  style={{ display: "block", marginTop: 2 }}
                >
                  {item.sub}
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.home.recentChats", "最近对话")}
          </div>
          {recent.length > 0 ? (
            <button
              type="button"
              className="m-section-more"
              onClick={() => navigate("/m/chat")}
            >
              {t("common.viewAll", "查看全部")}
            </button>
          ) : null}
        </div>

        {loading || fetching ? (
          <MobileSkeleton rows={3} />
        ) : failed ? (
          <MobileEmpty
            icon="alert"
            title={t("mobile.common.loadFailed", "加载失败")}
            description={t(
              "mobile.common.loadFailedDesc",
              "网络或后端暂时不可用。",
            )}
            action={
              <button
                type="button"
                className="m-btn m-btn--primary"
                onClick={() => void refreshAll()}
              >
                {t("common.retry", "重试")}
              </button>
            }
          />
        ) : recent.length === 0 ? (
          <MobileCard accent>
            <div className="m-card-title">
              {t("mobile.home.firstChatTitle", "开始第一次对话")}
            </div>
            <div className="m-card-desc">
              {t("mobile.home.firstChatDesc", {
                name:
                  activeAgent?.name ??
                  t("mobile.home.currentExpert", "当前专家"),
                defaultValue: "{{name}} 已经准备好，直接开聊。",
              })}
            </div>
            <button
              type="button"
              className="m-btn m-btn--primary m-mt16"
              onClick={() =>
                navigate(activeAgentId ? `/m/chat/${activeAgentId}` : "/m/chat")
              }
            >
              <MobileIcon name="chat" size={17} />
              {t("mobile.home.enterChat", "进入对话")}
            </button>
          </MobileCard>
        ) : (
          <div className="m-group">
            {recent.map((thread) => (
              <button
                type="button"
                key={thread.thread_id}
                className="m-row"
                onClick={() =>
                  activeAgentId &&
                  navigate(`/m/chat/${activeAgentId}/${thread.thread_id}`)
                }
              >
                <span className="m-row-main">
                  <span className="m-row-title">
                    {thread.turn_active ? <MobileDot tone="ok" /> : null}
                    {thread.awaiting_user ? <MobileDot tone="warn" /> : null}
                    {thread.title?.trim() || t("chat.newChat", "新建会话")}
                  </span>
                  <span className="m-row-sub">
                    {relativeTime(thread.last_active || thread.created_at)}
                  </span>
                </span>
                {thread.quick_chat || thread.workspace_kind === "quick" ? (
                  <MobileChip tone="accent">
                    {t("mobile.home.quickChat", "快速")}
                  </MobileChip>
                ) : null}
                <span className="m-row-chevron">
                  <MobileIcon name="chevron" size={16} />
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <MobileSheet
        open={agentSheet}
        title={t("mobile.home.switchExpert", "切换专家")}
        height="half"
        onClose={() => setAgentSheet(false)}
      >
        {agents.length === 0 ? (
          <MobileEmpty
            icon="experts"
            title={t("mobile.home.noExperts", "还没有专家")}
            description={t(
              "mobile.home.noExpertsDesc",
              "请先在桌面端创建并启动一个专家。",
            )}
          />
        ) : (
          <div className="m-group">
            {agents.map((agent) => (
              <button
                type="button"
                key={agent.agent_id}
                className="m-row"
                onClick={() => {
                  setActiveAgent(agent.agent_id);
                  setAgentSheet(false);
                }}
              >
                <MobileAvatar
                  name={agent.name}
                  src={agent.icon_url}
                  color={agent.color}
                  size={36}
                  square
                />
                <span className="m-row-main">
                  <span className="m-row-title">{agent.name}</span>
                  <span className="m-row-sub">
                    {agent.description ||
                      (agent.state === "running"
                        ? t("mobile.common.running", "运行中")
                        : t("mobile.common.stopped", "已停止"))}
                  </span>
                </span>
                {agent.state === "running" ? (
                  <MobileDot tone="ok" />
                ) : (
                  <MobileChip>
                    {t("mobile.common.stopped", "已停止")}
                  </MobileChip>
                )}
                {agent.agent_id === activeAgentId ? (
                  <MobileIcon name="check" size={17} />
                ) : null}
              </button>
            ))}
          </div>
        )}
      </MobileSheet>
    </MobilePage>
  );
}
