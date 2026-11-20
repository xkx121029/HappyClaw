import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { agentApi } from "../../api/modules/agent";
import { useAgent } from "../../context/AgentContext";
import { MobileEmpty } from "../components/MobileEmpty";
import { MobilePage } from "../components/MobilePage";
import { MobileSegmented } from "../components/MobileSegmented";
import { MobileSkeleton } from "../components/MobileSkeleton";

type Window = "7" | "30";
type UsageSummary = Awaited<ReturnType<typeof agentApi.getUsageSummary>>;

function formatTokens(value: number): string {
  if (!value) return "0";
  if (value < 1000) return String(value);
  if (value < 1_000_000) return `${(value / 1000).toFixed(1)}k`;
  return `${(value / 1_000_000).toFixed(2)}M`;
}

export function UsagePage() {
  const { t } = useTranslation();
  const { activeAgent, activeAgentId } = useAgent();
  const [windowDays, setWindowDays] = useState<Window>("7");
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setSummary(
        await agentApi.getUsageSummary({
          time_window: `${windowDays}d`,
          granularity: "day",
          top_n: 10,
        }),
      );
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [windowDays]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxTokens = useMemo(() => {
    if (!summary?.buckets?.length) return 1;
    return Math.max(1, ...summary.buckets.map((bucket) => bucket.total_tokens));
  }, [summary]);

  const topTurns = useMemo(() => {
    if (!summary?.buckets?.length) return [];
    return [...summary.buckets]
      .filter((bucket) => bucket.turns > 0)
      .sort((a, b) => b.total_tokens - a.total_tokens)
      .slice(0, 8);
  }, [summary]);

  return (
    <MobilePage
      title={t("mobile.usage.title", "用量")}
      back
      subtitle={activeAgent?.name ?? t("mobile.home.currentExpert", "当前专家")}
    >
      <MobileSegmented<Window>
        value={windowDays}
        onChange={setWindowDays}
        options={[
          { value: "7", label: t("mobile.usage.last7", "近 7 天") },
          { value: "30", label: t("mobile.usage.last30", "近 30 天") },
        ]}
      />

      <div className="m-mt16">
        {loading ? (
          <MobileSkeleton rows={3} />
        ) : failed ? (
          <MobileEmpty
            icon="alert"
            title={t("mobile.usage.loadFailedTitle", "用量数据加载失败")}
            action={
              <button
                type="button"
                className="m-btn m-btn--primary"
                onClick={() => void load()}
              >
                {t("common.retry", "重试")}
              </button>
            }
          />
        ) : !activeAgentId ? (
          <MobileEmpty
            icon="chart"
            title={t("mobile.tasks.noAgentTitle", "还没有选择专家")}
            description={t(
              "mobile.usage.noAgentDesc",
              "先选择一位专家，再查看它的 Token 用量。",
            )}
          />
        ) : !summary || summary.total_tokens === 0 ? (
          <MobileEmpty
            icon="chart"
            title={t("mobile.usage.emptyTitle", "还没有用量记录")}
            description={t(
              "mobile.usage.emptyDesc",
              "发起一次对话后，这里会显示 Token 统计。",
            )}
          />
        ) : (
          <>
            <div className="m-stats">
              <div className="m-stat">
                <div className="m-stat-value">
                  {formatTokens(summary.total_tokens)}
                </div>
                <div className="m-stat-label">
                  {t("mobile.usage.totalTokens", "总 Tokens")}
                </div>
              </div>
              <div className="m-stat">
                <div className="m-stat-value">
                  {formatTokens(summary.input_tokens)}
                </div>
                <div className="m-stat-label">
                  {t("mobile.usage.input", "输入")}
                </div>
              </div>
              <div className="m-stat">
                <div className="m-stat-value">
                  {formatTokens(summary.output_tokens)}
                </div>
                <div className="m-stat-label">
                  {t("mobile.usage.output", "输出")}
                </div>
              </div>
            </div>

            <div className="m-rowflex m-mt8" style={{ gap: 6 }}>
              <span className="m-hint">
                {t("mobile.usage.turnSummary", {
                  turns: summary.turns,
                  avg: formatTokens(Math.round(summary.avg_per_turn)),
                  defaultValue: "{{turns}} 轮对话 · 平均每轮 {{avg}}",
                })}
              </span>
            </div>

            <div className="m-section">
              <div className="m-section-head">
                <div className="m-section-title">
                  {t("mobile.usage.dailyTrend", "每日趋势")}
                </div>
                <span className="m-section-more">{summary.time_window}</span>
              </div>
              <div className="m-card">
                <div className="m-bars">
                  {summary.buckets.map((bucket) => (
                    <div className="m-bar-col" key={bucket.key}>
                      <div
                        className="m-bar"
                        style={{
                          height: `${Math.max(
                            2,
                            Math.round((bucket.total_tokens / maxTokens) * 100),
                          )}%`,
                        }}
                        title={`${bucket.label}: ${bucket.total_tokens}`}
                      />
                      <span className="m-bar-label">
                        {bucket.label.split(/[-/]/).slice(-2).join("/")}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {topTurns.length > 0 ? (
              <div className="m-section">
                <div className="m-section-head">
                  <div className="m-section-title">
                    {t("mobile.usage.topDays", "高消耗日期")}
                  </div>
                </div>
                <div className="m-group">
                  {topTurns.map((bucket) => (
                    <div className="m-row" key={bucket.key}>
                      <span className="m-row-main">
                        <span className="m-row-title">{bucket.label}</span>
                        <span className="m-row-sub">
                          {t("mobile.usage.turns", "{{n}} 轮对话", {
                            n: bucket.turns,
                          })}
                        </span>
                      </span>
                      <span className="m-row-meta">
                        {formatTokens(bucket.total_tokens)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </MobilePage>
  );
}
