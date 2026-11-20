import { useEffect, useState } from "react";
import {
  Button,
  Drawer,
  Descriptions,
  Badge,
  Tag,
  Typography,
  Divider,
  Alert,
  Empty,
  List,
  Spin,
} from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { MessageSquare } from "lucide-react";
import type { CronJobSpecOutput, OctopCronRun } from "../../../../api/types";
import { octopCronApi } from "../../../../api/modules/cronjob";
import { setPendingPrefillText } from "../../../Chat/hooks/chatStore";
import {
  channelFromSessionKey,
  classifyCronRunError,
  extractPromptFromJob,
  formatCronTimestamp,
} from "../cronDisplay";
import {
  formatTriggerText,
  lastRunStatusTag,
  oneShotPhase,
  oneShotPhaseLabelKey,
} from "../onceSchedule";

const { Text } = Typography;

type CronJob = CronJobSpecOutput;

interface JobDetailDrawerProps {
  open: boolean;
  job: CronJob | null;
  timeZone: string;
  onClose: () => void;
}

const RUN_TAG_COLORS: Record<string, string> = {
  running: "processing",
  ok: "success",
  error: "error",
  missed: "warning",
  skipped: "default",
};

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

export function JobDetailDrawer({
  open,
  job,
  timeZone,
  onClose,
}: JobDetailDrawerProps) {
  const { t } = useTranslation();
  const localizedRunError = (run: OctopCronRun): string | null => {
    if (!run.error) return null;
    const kind = classifyCronRunError(run);
    return kind === "unknown" ? run.error : t(`cronJobs.runError.${kind}`);
  };
  const navigate = useNavigate();
  const jobMeta = (job?.meta as Record<string, unknown> | undefined) ?? {};
  const detailAgentId =
    typeof jobMeta.orca_agent_id === "string" ? jobMeta.orca_agent_id : "";
  const [runs, setRuns] = useState<OctopCronRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  useEffect(() => {
    if (!open || !job?.id || !detailAgentId) {
      setRuns([]);
      return;
    }
    let cancelled = false;
    setRunsLoading(true);
    octopCronApi
      .runs(detailAgentId, job.id, 20)
      .then((items) => {
        if (!cancelled) setRuns(items);
      })
      .catch((error) => {
        console.error("Failed to load cron runs", error);
        if (!cancelled) setRuns([]);
      })
      .finally(() => {
        if (!cancelled) setRunsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, job?.id, detailAgentId]);

  if (!job) return null;

  const meta = jobMeta;
  const sessionKey =
    typeof meta.octop_session_key === "string" ? meta.octop_session_key : "";
  const channel = sessionKey
    ? channelFromSessionKey(sessionKey)
    : String(job.dispatch?.channel || "—");
  const agentPrompt = extractPromptFromJob(job) || null;
  const lastStatus =
    typeof meta.octop_last_status === "string" ? meta.octop_last_status : "";
  const phase = oneShotPhase(
    job.schedule?.cron,
    Boolean(job.enabled),
    lastStatus,
  );
  const statusTag = lastStatus ? lastRunStatusTag(lastStatus) : null;
  const triggerLabel = formatTriggerText(job.schedule?.cron, {
    mail: t("cronJobs.form.agentlyNewMail"),
    once: t("cronJobs.form.scheduleModeOnce"),
  });
  const lastError =
    typeof meta.octop_last_error === "string" && meta.octop_last_error.trim()
      ? meta.octop_last_error
      : null;
  const lastErrorKind = lastError
    ? classifyCronRunError({ status: lastStatus ?? "", error: lastError })
    : "unknown";
  const lastErrorText =
    lastError && lastErrorKind !== "unknown"
      ? t(`cronJobs.runError.${lastErrorKind}`)
      : lastError;

  const handleGoToChat = () => {
    onClose();
    setPendingPrefillText(agentPrompt ?? "");
    navigate("/chat", { state: { prefillInput: agentPrompt ?? "" } });
  };

  return (
    <Drawer
      title={
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Badge
            status={job.enabled ? "success" : "default"}
            text={
              <span style={{ fontWeight: 600, fontSize: "var(--fn-text-md)" }}>
                {job.name || job.id}
              </span>
            }
          />
        </div>
      }
      open={open}
      onClose={onClose}
      width={480}
      destroyOnHidden
      footer={
        agentPrompt ? (
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <Button
              type="primary"
              icon={<MessageSquare size={14} />}
              onClick={handleGoToChat}
            >
              {t("cronJobs.goToChat", "发送到聊天")}
            </Button>
          </div>
        ) : null
      }
    >
      {/* Basic information */}
      <Divider
        orientation="left"
        orientationMargin={0}
        style={{ fontSize: "var(--fn-text-xs)", fontWeight: 600, marginTop: 0 }}
      >
        {t("cronJobs.form.sectionBasic")}
      </Divider>
      <Descriptions
        column={1}
        size="small"
        labelStyle={{ color: "var(--fn-text-tertiary)", width: 120 }}
      >
        <Descriptions.Item label={t("cronJobs.col.id")}>
          <Text copyable style={{ fontSize: 12, fontFamily: "monospace" }}>
            {job.id}
          </Text>
        </Descriptions.Item>
        <Descriptions.Item label={t("cronJobs.col.name")}>
          {job.name || "—"}
        </Descriptions.Item>
        <Descriptions.Item label={t("common.enabled")}>
          {phase ? (
            <Tag
              color={
                phase === "pending"
                  ? "success"
                  : phase === "failed"
                  ? "error"
                  : phase === "missed"
                  ? "warning"
                  : "default"
              }
            >
              {t(oneShotPhaseLabelKey(phase))}
            </Tag>
          ) : job.enabled ? (
            <Tag color="success">{t("common.enabled")}</Tag>
          ) : (
            <Tag color="default">{t("common.disabled")}</Tag>
          )}
        </Descriptions.Item>
      </Descriptions>

      {/* Schedule settings */}
      <Divider
        orientation="left"
        orientationMargin={0}
        style={{ fontSize: "var(--fn-text-xs)", fontWeight: 600 }}
      >
        {t("cronJobs.form.sectionSchedule")}
      </Divider>
      <Descriptions
        column={1}
        size="small"
        labelStyle={{ color: "var(--fn-text-tertiary)", width: 120 }}
      >
        <Descriptions.Item label={t("cronJobs.col.trigger")}>
          <Text code style={{ fontSize: 12 }}>
            {triggerLabel}
          </Text>
        </Descriptions.Item>
        <Descriptions.Item label={t("cronJobs.form.timezone")}>
          {job.schedule?.timezone || "—"}
        </Descriptions.Item>
        <Descriptions.Item label={t("cronJobs.col.nextRunAt")}>
          {formatCronTimestamp(
            typeof meta.octop_next_run_at === "number"
              ? meta.octop_next_run_at
              : null,
            timeZone,
          )}
        </Descriptions.Item>
        <Descriptions.Item label={t("cronJobs.col.lastRunAt")}>
          {formatCronTimestamp(
            typeof meta.octop_last_run_at === "number"
              ? meta.octop_last_run_at
              : null,
            timeZone,
          )}
        </Descriptions.Item>
        <Descriptions.Item label={t("cronJobs.col.lastStatus")}>
          {lastStatus ? (
            <Tag color={statusTag?.color ?? "default"}>
              {statusTag ? t(statusTag.labelKey) : lastStatus}
            </Tag>
          ) : (
            "—"
          )}
        </Descriptions.Item>
        <Descriptions.Item label={t("cronJobs.form.maxRetries")}>
          {`${meta.octop_max_retries ?? 0} · ${t("cronJobs.form.retryBackoff")} ${
            meta.octop_retry_backoff_seconds ?? 60
          }s`}
        </Descriptions.Item>
        <Descriptions.Item label={t("cronJobs.form.catchUpMisses")}>
          {String(meta.octop_catch_up_misses ?? 0)}
        </Descriptions.Item>
        {lastError && (
          <Descriptions.Item label={t("cronJobs.col.lastError")}>
            <Alert
              type="error"
              showIcon
              message={
                <Text
                  title={lastError ?? undefined}
                  style={{
                    fontSize: 12,
                    whiteSpace: "pre-wrap",
                    cursor: "help",
                  }}
                >
                  {lastErrorText}
                </Text>
              }
              style={{ padding: "8px 12px" }}
            />
          </Descriptions.Item>
        )}
      </Descriptions>

      <Divider
        orientation="left"
        orientationMargin={0}
        style={{ fontSize: "var(--fn-text-xs)", fontWeight: 600 }}
      >
        {t("cronJobs.runHistory")}
      </Divider>
      <Text
        type="secondary"
        style={{ fontSize: 12, display: "block", marginBottom: 8 }}
      >
        {t("cronJobs.runHistoryHint")}
      </Text>
      {runsLoading ? (
        <div style={{ padding: "12px 0", textAlign: "center" }}>
          <Spin size="small" />
        </div>
      ) : runs.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("cronJobs.runHistoryEmpty")}
            </Text>
          }
        />
      ) : (
        <List
          size="small"
          dataSource={runs}
          renderItem={(run) => (
            <List.Item style={{ padding: "8px 0", alignItems: "flex-start" }}>
              <div style={{ width: "100%" }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 8,
                    alignItems: "center",
                  }}
                >
                  <Tag
                    color={RUN_TAG_COLORS[run.status] ?? "default"}
                    style={{ margin: 0, fontSize: "var(--fn-text-2xs)" }}
                  >
                    {t(`cronJobs.runStatus.${run.status}`, run.status)}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {formatCronTimestamp(run.started_at, timeZone)}
                  </Text>
                </div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t(`cronJobs.triggerKind.${run.trigger_kind}`, run.trigger_kind)}
                  {run.duration_ms != null
                    ? ` · ${formatDuration(run.duration_ms)}`
                    : ""}
                  {run.attempt > 1
                    ? ` · ${t("cronJobs.attemptN", { n: run.attempt })}`
                    : ""}
                </Text>
                {run.note && (
                  <div
                    style={{
                      fontSize: 12,
                      color: "var(--fn-color-warning-text)",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                    }}
                  >
                    {run.note}
                  </div>
                )}
                {run.error && (
                  <div
                    title={run.error}
                    style={{
                      fontSize: 12,
                      color: "var(--fn-color-error, #ef4444)",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      cursor: "help",
                    }}
                  >
                    {localizedRunError(run)}
                  </div>
                )}
              </div>
            </List.Item>
          )}
        />
      )}

      <Divider
        orientation="left"
        orientationMargin={0}
        style={{ fontSize: "var(--fn-text-xs)", fontWeight: 600 }}
      >
        {t("cronJobs.form.sectionTask")}
      </Divider>
      <Descriptions
        column={1}
        size="small"
        labelStyle={{ color: "var(--fn-text-tertiary)", width: 120 }}
      >
        <Descriptions.Item label={t("cronJobs.col.taskType")}>
          {job.task_type === "text"
            ? t("cronJobs.form.taskTypeText")
            : t("cronJobs.form.taskTypeAgent")}
        </Descriptions.Item>
        {agentPrompt && (
          <Descriptions.Item label={t("cronJobs.col.prompt")}>
            <Text style={{ whiteSpace: "pre-wrap", fontSize: "var(--fn-text-xs)" }}>
              {agentPrompt}
            </Text>
          </Descriptions.Item>
        )}
        {job.model || meta.octop_model ? (
          <Descriptions.Item label={t("cronJobs.form.model")}>
            {String(job.model || meta.octop_model)}
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label={t("cronJobs.col.freshThread")}>
          {meta.octop_fresh_thread
            ? t("cronJobs.col.freshThreadOn")
            : t("cronJobs.col.freshThreadOff")}
        </Descriptions.Item>
      </Descriptions>

      <Divider
        orientation="left"
        orientationMargin={0}
        style={{ fontSize: "var(--fn-text-xs)", fontWeight: 600 }}
      >
        {t("cronJobs.form.sectionRouting")}
      </Divider>
      <Descriptions
        column={1}
        size="small"
        labelStyle={{ color: "var(--fn-text-tertiary)", width: 120 }}
      >
        <Descriptions.Item label={t("cronJobs.col.dispatchChannel")}>
          {channel}
        </Descriptions.Item>
        {sessionKey && (
          <Descriptions.Item label={t("cronJobs.col.sessionKey")}>
            <Text copyable style={{ fontSize: 12, fontFamily: "monospace" }}>
              {sessionKey}
            </Text>
          </Descriptions.Item>
        )}
      </Descriptions>
    </Drawer>
  );
}
