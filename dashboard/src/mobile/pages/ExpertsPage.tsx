import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAgent } from "../../context/AgentContext";
import { MobileAvatar } from "../components/MobileAvatar";
import { MobileChip, MobileDot } from "../components/MobileChip";
import { MobileEmpty } from "../components/MobileEmpty";
import { MobileIcon } from "../components/MobileIcon";
import { MobilePage } from "../components/MobilePage";
import { MobileSegmented } from "../components/MobileSegmented";
import { MobileSkeleton } from "../components/MobileSkeleton";
import { showMobileToast } from "../components/MobileToast";

type Filter = "all" | "running" | "stopped";

export function ExpertsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { agents, activeAgentId, loading, refresh, setActiveAgent } =
    useAgent();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [refreshing, setRefreshing] = useState(false);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return agents.filter((agent) => {
      if (filter === "running" && agent.state !== "running") return false;
      if (filter === "stopped" && agent.state === "running") return false;
      if (!keyword) return true;
      return (
        agent.name.toLowerCase().includes(keyword) ||
        (agent.description ?? "").toLowerCase().includes(keyword)
      );
    });
  }, [agents, filter, query]);

  const openAgent = (agentId: string, state: string) => {
    if (state !== "running") {
      showMobileToast(
        t("mobile.experts.notRunning", "该专家未运行，请先在桌面端启动"),
      );
      return;
    }
    setActiveAgent(agentId);
    navigate(`/m/chat/${agentId}`);
  };

  return (
    <MobilePage
      title={t("mobile.nav.experts", "专家")}
      subtitle={t("mobile.experts.subtitle", "选择一位专家开始对话")}
      actions={
        <button
          type="button"
          className="m-iconbtn"
          aria-label={t("common.refresh", "刷新")}
          onClick={async () => {
            setRefreshing(true);
            await refresh({ force: true });
            setRefreshing(false);
          }}
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
      }
    >
      <div className="m-search">
        <MobileIcon name="search" size={17} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("mobile.experts.searchPlaceholder", "搜索专家")}
          aria-label={t("mobile.experts.searchPlaceholder", "搜索专家")}
        />
        {query ? (
          <button
            type="button"
            aria-label={t("mobile.experts.clearSearch", "清空")}
            onClick={() => setQuery("")}
            style={{ display: "flex" }}
          >
            <MobileIcon name="close" size={15} />
          </button>
        ) : null}
      </div>

      <div className="m-mt16">
        <MobileSegmented<Filter>
          value={filter}
          onChange={setFilter}
          options={[
            {
              value: "all",
              label: t("mobile.experts.filterAll", "全部 {{n}}", {
                n: agents.length,
              }),
            },
            {
              value: "running",
              label: t("mobile.experts.filterRunning", "运行中 {{n}}", {
                n: agents.filter((agent) => agent.state === "running").length,
              }),
            },
            {
              value: "stopped",
              label: t("mobile.experts.filterStopped", "已停止 {{n}}", {
                n: agents.filter((agent) => agent.state !== "running").length,
              }),
            },
          ]}
        />
      </div>

      <div className="m-section">
        {loading ? (
          <MobileSkeleton rows={4} />
        ) : filtered.length === 0 ? (
          <MobileEmpty
            icon="experts"
            title={
              agents.length === 0
                ? t("mobile.experts.noExpertTitle", "还没有专家")
                : t("mobile.experts.noMatchTitle", "没有匹配的专家")
            }
            description={
              agents.length === 0
                ? t(
                    "mobile.experts.noExpertsDesc",
                    "先在桌面端创建一位专家，然后回到手机端对话。",
                  )
                : t("mobile.experts.noMatchDesc", "换个关键词或筛选条件试试。")
            }
            secondary={
              agents.length === 0 ? undefined : (
                <button
                  type="button"
                  className="m-btn"
                  onClick={() => {
                    setQuery("");
                    setFilter("all");
                  }}
                >
                  {t("mobile.experts.clearFilters", "清除筛选")}
                </button>
              )
            }
          />
        ) : (
          <div className="m-stack">
            {filtered.map((agent) => {
              const running = agent.state === "running";
              return (
                <button
                  type="button"
                  key={agent.agent_id}
                  className="m-card is-tap"
                  onClick={() => openAgent(agent.agent_id, agent.state)}
                  style={{ textAlign: "left" }}
                >
                  <div className="m-rowflex">
                    <MobileAvatar
                      name={agent.name}
                      src={agent.icon_url}
                      color={agent.color}
                      size={44}
                      square
                    />
                    <div className="m-grow">
                      <div className="m-spread">
                        <span
                          className="m-card-title m-truncate"
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          {agent.name}
                          {agent.agent_id === activeAgentId ? (
                            <MobileChip tone="accent">
                              {t("mobile.experts.current", "当前")}
                            </MobileChip>
                          ) : null}
                        </span>
                        {running ? (
                          <span className="m-rowflex" style={{ gap: 5 }}>
                            <MobileDot tone="ok" />
                            <span className="m-hint">
                              {t("mobile.common.running", "运行中")}
                            </span>
                          </span>
                        ) : (
                          <MobileChip>
                            {t("mobile.common.stopped", "已停止")}
                          </MobileChip>
                        )}
                      </div>
                      <div
                        className="m-card-desc m-clamp2"
                        style={{ marginTop: 4 }}
                      >
                        {agent.description ||
                          t("mobile.experts.noDescription", "暂无简介")}
                      </div>
                    </div>
                  </div>
                  <div
                    className="m-rowflex m-wrap"
                    style={{ marginTop: 12, gap: 6 }}
                  >
                    {agent.kind === "team" ? (
                      <MobileChip>
                        {t("mobile.experts.team", "团队")}
                      </MobileChip>
                    ) : null}
                    {agent.bridge ? (
                      <MobileChip>
                        {t("mobile.experts.remote", "远程")}
                      </MobileChip>
                    ) : null}
                    {agent.unread_count ? (
                      <MobileChip tone="warn">
                        {t("mobile.experts.unreadCount", "{{n}} 条未读", {
                          n: agent.unread_count,
                        })}
                      </MobileChip>
                    ) : null}
                    {typeof agent.mcp_servers?.length === "number" &&
                    agent.mcp_servers.length > 0 ? (
                      <MobileChip>
                        {t("mobile.experts.connectorCount", "{{n}} 个连接器", {
                          n: agent.mcp_servers.length,
                        })}
                      </MobileChip>
                    ) : null}
                    {agent.default_model ? (
                      <MobileChip>{agent.default_model}</MobileChip>
                    ) : null}
                    <span className="m-grow" />
                    <MobileIcon name="chevron" size={16} />
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </MobilePage>
  );
}
