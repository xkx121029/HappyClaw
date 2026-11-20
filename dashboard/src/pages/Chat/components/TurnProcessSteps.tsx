import { useEffect, useMemo, useRef, useState } from "react";
import { Brain, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import Markdown from "../../../components/Markdown/LazyMarkdown";
import type { ChatMessage } from "../hooks/useChat";
import type { TurnStep } from "../utils/turnBlocks";
import { formatStepDuration, isStepFailed } from "../utils/turnBlocks";
import { useCollapseThinking } from "../hooks/useCollapseThinking";
import {
  resolveDeferredToolLabel,
  resolveToolLabel,
  useToolDisplayNames,
} from "../hooks/toolDisplayNames";
import { useAgent } from "../../../context/AgentContext";
import { isTeamAgent, isTeamHostSpeaker } from "../../../utils/teamAgent";
import { rewritePeerSpeakerId } from "../../../utils/remoteExpert";
import { ToolDetailsInline } from "./MessageBubble";
import { DecisionToolRow } from "./AssistantProcessSummary";
import { ExpertMessageAvatar } from "./MessageSender";
import styles from "../index.module.less";

interface ThinkingStepRowProps {
  content: string;
  live: boolean;
  /** Display preference: thinking collapsed by default. */
  collapsed: boolean;
  isStreaming: boolean;
}

function ThinkingStepRow({
  content,
  live,
  collapsed,
  isStreaming,
}: ThinkingStepRowProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(!collapsed);
  const previousCollapsed = useRef(collapsed);

  useEffect(() => {
    if (previousCollapsed.current === collapsed) return;
    previousCollapsed.current = collapsed;
    setExpanded(!collapsed);
  }, [collapsed]);

  return (
    <div className={cx(styles.turnStepRow, live && styles.turnStepRowLive)}>
      <button
        type="button"
        className={cx(
          styles.inlineToolSummary,
          live && styles.inlineToolSummaryRunning,
        )}
        onClick={() => setExpanded((open) => !open)}
        aria-expanded={expanded}
        aria-busy={live || undefined}
      >
        <span
          className={styles.inlineToolIcon}
          aria-label={t("chat.thinkingStep", { defaultValue: "思考" })}
        >
          <Brain size={14} strokeWidth={2.2} aria-hidden />
        </span>
        <span className={styles.inlineToolName}>
          {live
            ? t("chat.processThinkingLive", { defaultValue: "深度思考中" })
            : t("chat.thinkingStep", { defaultValue: "思考" })}
        </span>
        {live ? (
          <span className={styles.inlineToolLiveDots} aria-hidden>
            <span className={styles.thinkingDot} />
            <span className={styles.thinkingDot} />
            <span className={styles.thinkingDot} />
          </span>
        ) : null}
        <ChevronRight
          size={14}
          className={cx(
            styles.inlineToolChevron,
            expanded && styles.inlineToolChevronOpen,
          )}
        />
      </button>
      {expanded ? (
        <div className={cx(styles.inlineToolDetails, styles.turnThinkingBody)}>
          <Markdown content={content} isStreaming={live && isStreaming} />
        </div>
      ) : null}
    </div>
  );
}

interface ToolStepRowProps {
  message: ChatMessage;
  isStreaming: boolean;
  onAcpPermissionSelect?: (message: string) => void;
  hideToolMedia: boolean;
  agentId: string | null;
}

function ToolStepRow({
  message,
  isStreaming,
  onAcpPermissionSelect,
  hideToolMedia,
  agentId,
}: ToolStepRowProps) {
  if (!message.toolData) return null;
  const failed = isStepFailed({ kind: "tool", id: message.id, message });
  return (
    <div
      className={cx(styles.turnStepRow, failed && styles.turnStepRowFailed)}
      data-turn-step-state={failed ? "failed" : undefined}
    >
      <ToolDetailsInline
        toolData={message.toolData}
        isStreaming={message.status === "streaming" && isStreaming}
        onAcpPermissionSelect={onAcpPermissionSelect}
        hideMediaPreview={hideToolMedia}
        agentId={agentId}
        forceError={failed}
      />
    </div>
  );
}

export interface ProcessStepListProps {
  steps: TurnStep[];
  isStreaming: boolean;
  isTeam: boolean;
  onAcpPermissionSelect?: (message: string) => void;
  hideToolMedia: boolean;
  agentId: string | null;
}

/** Per-step one-line rows: thinking, the decision pass, and each tool call. */
export function ProcessStepList({
  steps,
  isStreaming,
  isTeam,
  onAcpPermissionSelect,
  hideToolMedia,
  agentId,
}: ProcessStepListProps) {
  const [collapseThinking] = useCollapseThinking(isTeam);
  return (
    <div className={styles.turnStepList} data-turn-steps="">
      {steps.map((step) => {
        if (step.kind === "decision") {
          return (
            <div key={step.id} className={styles.turnStepRow}>
              <DecisionToolRow notice={step.notice} />
            </div>
          );
        }
        if (step.kind === "thinking") {
          return (
            <ThinkingStepRow
              key={step.id}
              content={step.item.content}
              live={Boolean(step.item.isStreaming) && isStreaming}
              collapsed={collapseThinking}
              isStreaming={isStreaming}
            />
          );
        }
        return (
          <ToolStepRow
            key={step.id}
            message={step.message}
            isStreaming={isStreaming}
            onAcpPermissionSelect={onAcpPermissionSelect}
            hideToolMedia={hideToolMedia}
            agentId={agentId}
          />
        );
      })}
    </div>
  );
}

interface FoldedProcessGroupProps extends ProcessStepListProps {
  durationMs: number | null;
  failedCount: number;
}

/**
 * Earlier thinking/tool runs folded into one row after a later text segment
 * arrives. Collapsed by default; expanding restores every step untouched.
 */
export function FoldedProcessGroup({
  durationMs,
  failedCount,
  ...listProps
}: FoldedProcessGroupProps) {
  const { t } = useTranslation();
  const displayNames = useToolDisplayNames();
  const [expanded, setExpanded] = useState(false);
  const count = listProps.steps.length;
  // Name the failed steps: "有失败" alone does not tell the user which one.
  const failedNames = useMemo(
    () =>
      listProps.steps
        .filter(isStepFailed)
        .map((step) => {
          if (step.kind !== "tool") return "";
          const toolData = step.message.toolData;
          return (
            resolveDeferredToolLabel(
              toolData?.name,
              toolData?.arguments,
              displayNames,
            ) ??
            resolveToolLabel(
              toolData?.name ?? "",
              toolData?.displayName,
              displayNames,
            )
          );
        })
        .filter(Boolean),
    [listProps.steps, displayNames],
  );
  const failedSummary =
    failedNames.length > 2
      ? t("chat.processGroupFailedMore", {
          names: failedNames.slice(0, 2).join("、"),
          count: failedNames.length,
          defaultValue: "{{names}} 等 {{count}} 项",
        })
      : failedNames.join("、");
  const summary = durationMs
    ? t("chat.processGroupSummaryDuration", {
        count,
        duration: formatStepDuration(durationMs),
        defaultValue: "已执行 {{count}} 步，用时 {{duration}}",
      })
    : t("chat.processGroupSummary", {
        count,
        defaultValue: "已执行 {{count}} 步",
      });

  return (
    <div className={styles.processSummary} data-turn-fold="group">
      <button
        type="button"
        className={styles.processSummaryToggle}
        onClick={() => setExpanded((open) => !open)}
        aria-expanded={expanded}
      >
        <span className={styles.processSummaryText}>
          {failedCount > 0 ? (
            <span className={styles.turnFailedDot} aria-hidden="true" />
          ) : null}
          {summary}
          {failedCount > 0 && failedSummary ? (
            <span className={styles.turnFailedChip}>
              {t("chat.processGroupFailedNames", {
                names: failedSummary,
                defaultValue: "失败：{{names}}",
              })}
            </span>
          ) : null}
        </span>
        <ChevronRight
          size={14}
          className={cx(
            styles.processSummaryChevron,
            expanded && styles.processSummaryChevronOpen,
          )}
        />
      </button>
      {expanded ? (
        <div className={styles.processSummaryBody}>
          <ProcessStepList {...listProps} />
        </div>
      ) : null}
    </div>
  );
}

interface ProcessStepGroupProps extends Omit<ProcessStepListProps, "isTeam"> {
  showAvatar: boolean;
  merged?: boolean;
  durationMs?: number | null;
  failedCount?: number;
}

/** One avatar column + the step rows (or the folded summary row). */
export function ProcessStepGroup({
  showAvatar,
  merged = false,
  durationMs = null,
  failedCount = 0,
  agentId,
  ...listProps
}: ProcessStepGroupProps) {
  const { t } = useTranslation();
  const { agents, activeAgent } = useAgent();
  const isTeamRoom = isTeamAgent(activeAgent);
  const speakerId =
    rewritePeerSpeakerId(activeAgent?.agent_id, agentId) || agentId;
  const hostSpeaker = isTeamHostSpeaker(
    isTeamRoom,
    speakerId,
    activeAgent?.agent_id,
  );
  const expert =
    (speakerId && agents.find((item) => item.agent_id === speakerId)) ||
    (!isTeamRoom || hostSpeaker ? activeAgent : undefined);
  const avatarTooltip = hostSpeaker
    ? t("chat.teamHostHover", { name: activeAgent?.name || expert?.name || "" })
    : expert?.name || undefined;
  const avatarProfileId = hostSpeaker
    ? activeAgent?.agent_id
    : speakerId || undefined;

  return (
    <div className={styles.turnProcessRow}>
      {showAvatar && (expert || avatarProfileId) ? (
        <div className={styles.avatarCol}>
          <ExpertMessageAvatar
            name={expert?.name || avatarProfileId}
            color={expert?.color}
            iconName={expert?.icon_name}
            iconUrl={expert?.icon_url}
            tooltip={avatarTooltip}
            profileAgentId={avatarProfileId}
          />
        </div>
      ) : null}
      <div className={styles.turnProcessBody}>
        {merged ? (
          <FoldedProcessGroup
            {...listProps}
            agentId={agentId}
            isTeam={isTeamRoom}
            durationMs={durationMs}
            failedCount={failedCount}
          />
        ) : (
          <ProcessStepList
            {...listProps}
            agentId={agentId}
            isTeam={isTeamRoom}
          />
        )}
      </div>
    </div>
  );
}
