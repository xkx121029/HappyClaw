import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { octopCronApi } from "../../api/modules/cronjob";
import type { OctopCronRow, OctopCronRun } from "../../api/types";
import { useAgent } from "../../context/AgentContext";
import { MobileChip } from "../components/MobileChip";
import { MobileEmpty } from "../components/MobileEmpty";
import { MobileIcon } from "../components/MobileIcon";
import { MobilePage } from "../components/MobilePage";
import { MobileSheet } from "../components/MobileSheet";
import { MobileSkeleton } from "../components/MobileSkeleton";
import { MobileSwitch } from "../components/MobileSwitch";
import { showMobileToast } from "../components/MobileToast";

type Tone = "ok" | "warn" | "danger" | "accent";

const RUN_TONE: Record<string, Tone> = {
  ok: "ok",
  running: "accent",
  missed: "warn",
  skipped: "warn",
  error: "danger",
};

const STATUS_TONE: Record<string, "ok" | "warn" | "danger"> = {
  ok: "ok",
  success: "ok",
  error: "danger",
  failed: "danger",
  missed: "warn",
};

function formatEpoch(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return "—";
  const date = new Date(epochSeconds * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getMonth() + 1}/${date.getDate()} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

function formatDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m${Math.round((ms % 60_000) / 1000)}s`;
}

export function TasksPage() {
  const { t } = useTranslation();
  const { activeAgentId, activeAgent, loading: agentsLoading } = useAgent();
  const [rows, setRows] = useState<OctopCronRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [runsTarget, setRunsTarget] = useState<OctopCronRow | null>(null);
  const [runs, setRuns] = useState<OctopCronRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const runLabels = useMemo<Record<string, string>>(
    () => ({
      ok: t("mobile.tasks.runOk", "成功"),
      running: t("mobile.common.running", "运行中"),
      missed: t("mobile.tasks.runMissed", "错过"),
      skipped: t("mobile.tasks.runSkipped", "跳过"),
      error: t("mobile.tasks.runError", "失败"),
    }),
    [t],
  );

  const load = useCallback(async () => {
    if (!activeAgentId) {
      setRows([]);
      setLoading(false);
      return;
    }
    try {
      const list = await octopCronApi.list(activeAgentId);
      setRows(list);
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [activeAgentId]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  const toggle = async (row: OctopCronRow) => {
    if (!activeAgentId) return;
    const next = !row.enabled;
    setRows((prev) =>
      prev.map((item) =>
        item.id === row.id ? { ...item, enabled: next } : item,
      ),
    );
    try {
      await octopCronApi.patch(activeAgentId, row.id, { enabled: next });
    } catch {
      setRows((prev) =>
        prev.map((item) =>
          item.id === row.id ? { ...item, enabled: row.enabled } : item,
        ),
      );
      showMobileToast(t("mobile.tasks.toggleFailed", "更新任务状态失败"));
    }
  };

  const runNow = async (row: OctopCronRow) => {
    if (!activeAgentId || busyId) return;
    setBusyId(row.id);
    try {
      await octopCronApi.runNow(activeAgentId, row.id);
      showMobileToast(t("mobile.tasks.triggered", "已触发运行"));
      window.setTimeout(() => void load(), 800);
    } catch {
      showMobileToast(t("mobile.tasks.triggerFailed", "触发运行失败"));
    } finally {
      setBusyId(null);
    }
  };

  const openRuns = async (row: OctopCronRow) => {
    if (!activeAgentId) return;
    setRunsTarget(row);
    setRuns([]);
    setRunsLoading(true);
    try {
      setRuns(await octopCronApi.runs(activeAgentId, row.id, 20));
    } catch {
      showMobileToast(t("mobile.tasks.runsFailed", "运行记录加载失败"));
    } finally {
      setRunsLoading(false);
    }
  };

  return (
    <MobilePage
      title={t("mobile.nav.tasks", "任务")}
      back
      subtitle={activeAgent?.name}
    >
      {loading || agentsLoading ? (
        <MobileSkeleton rows={3} />
      ) : !activeAgentId ? (
        <MobileEmpty
          icon="clock"
          title={t("mobile.tasks.noAgentTitle", "还没有选择专家")}
          description={t(
            "mobile.tasks.noAgentDesc",
            "先在桌面端启动一个专家，再管理它的定时任务。",
          )}
        />
      ) : failed ? (
        <MobileEmpty
          icon="alert"
          title={t("mobile.tasks.loadFailedTitle", "任务加载失败")}
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
      ) : rows.length === 0 ? (
        <MobileEmpty
          icon="clock"
          title={t("mobile.tasks.emptyTitle", "还没有定时任务")}
          description={t(
            "mobile.tasks.emptyDesc",
            "定时任务可在桌面端创建，这里可以启停、立即运行和查看记录。",
          )}
        />
      ) : (
        <div className="m-stack">
          {rows.map((row) => {
            const tone = row.last_status
              ? STATUS_TONE[row.last_status] ?? "warn"
              : "warn";
            const statusTone = row.last_status
              ? STATUS_TONE[row.last_status]
              : undefined;
            const lastRunText = !row.enabled
              ? t("mobile.tasks.disabled", "已停用")
              : row.last_status
              ? statusTone === "ok"
                ? t("mobile.tasks.lastOk", "上次成功")
                : statusTone === "danger"
                ? t("mobile.tasks.lastFailed", "上次失败")
                : t("mobile.tasks.lastWarn", "上次异常")
              : t("mobile.tasks.neverRun", "未运行");
            return (
              <div className="m-card" key={row.id}>
                <div className="m-spread">
                  <div className="m-grow">
                    <div className="m-card-title m-truncate">
                      {row.name?.trim() ||
                        row.prompt.slice(0, 24) ||
                        t("mobile.tasks.untitled", "未命名任务")}
                    </div>
                    <div className="m-card-desc">
                      {row.trigger}
                      {" · "}
                      {row.task_type === "text"
                        ? t("mobile.tasks.typeText", "文本任务")
                        : t("mobile.tasks.typeAgent", "代理任务")}
                      {row.timezone ? ` · ${row.timezone}` : ""}
                    </div>
                  </div>
                  <MobileSwitch
                    checked={row.enabled}
                    onChange={() => void toggle(row)}
                    label={t("mobile.tasks.enableLabel", "启用 {{name}}", {
                      name: row.name,
                    })}
                  />
                </div>
                <div
                  className="m-rowflex m-wrap"
                  style={{ marginTop: 10, gap: 6 }}
                >
                  <MobileChip tone={row.enabled ? tone : "default"}>
                    {lastRunText}
                  </MobileChip>
                  <MobileChip>
                    {t("mobile.tasks.nextRun", "下次 {{time}}", {
                      time: formatEpoch(row.next_run_at),
                    })}
                  </MobileChip>
                  {row.last_error ? (
                    <MobileChip tone="danger">
                      {t("mobile.tasks.hasError", "有错误")}
                    </MobileChip>
                  ) : null}
                </div>
                <div className="m-rowflex" style={{ marginTop: 12 }}>
                  <button
                    type="button"
                    className="m-btn"
                    disabled={busyId === row.id}
                    onClick={() => void runNow(row)}
                  >
                    <MobileIcon name="play" size={15} />
                    {busyId === row.id
                      ? t("mobile.tasks.triggering", "触发中…")
                      : t("mobile.tasks.runNow", "立即运行")}
                  </button>
                  <button
                    type="button"
                    className="m-btn m-btn--ghost"
                    onClick={() => void openRuns(row)}
                  >
                    <MobileIcon name="list" size={15} />
                    {t("mobile.tasks.runHistory", "运行记录")}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <MobileSheet
        open={Boolean(runsTarget)}
        title={
          runsTarget
            ? t("mobile.tasks.runsTitleNamed", "运行记录 · {{name}}", {
                name:
                  runsTarget.name || t("mobile.tasks.untitled", "未命名任务"),
              })
            : t("mobile.tasks.runHistory", "运行记录")
        }
        height="half"
        onClose={() => setRunsTarget(null)}
      >
        {runsLoading ? (
          <MobileSkeleton rows={3} />
        ) : runs.length === 0 ? (
          <MobileEmpty
            icon="list"
            title={t("mobile.tasks.noRuns", "还没有运行记录")}
          />
        ) : (
          <div className="m-group">
            {runs.map((run) => (
              <div className="m-row" key={run.run_id}>
                <span className="m-row-main">
                  <span className="m-row-title">
                    <MobileChip tone={RUN_TONE[run.status] ?? "default"}>
                      {runLabels[run.status] ?? run.status}
                    </MobileChip>
                    {run.trigger_kind === "manual"
                      ? t("mobile.tasks.manual", "手动")
                      : t("mobile.tasks.scheduled", "定时")}
                  </span>
                  <span className="m-row-sub">
                    {formatEpoch(run.started_at)}
                    {run.duration_ms !== null
                      ? ` · ${formatDuration(run.duration_ms)}`
                      : ""}
                  </span>
                  {run.error ? (
                    <span
                      className="m-row-sub"
                      style={{ color: "var(--m-danger)" }}
                    >
                      {run.error}
                    </span>
                  ) : null}
                </span>
              </div>
            ))}
          </div>
        )}
      </MobileSheet>
    </MobilePage>
  );
}
