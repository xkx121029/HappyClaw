import { Fragment, useMemo } from "react";
import { ChevronRight, FilePen, Globe } from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import type { HitlDecisionHandler } from "../../../api/types/hitl";
import type { ChatMessage } from "../hooks/useChat";
import {
  splitAssistantTurn,
  turnUsedBrowserTool,
  turnUsedFileTool,
} from "../utils/messageContent";
import { isWriteToolName } from "../constants";
import { collectChatFilePaths } from "../hooks/useChatFileDetection";
import { useAgent } from "../../../context/AgentContext";
import { TodoProgressPanel } from "../../../components/TodoProgressPanel";
import {
  collectWriteTodosFromMessages,
  isWriteTodosToolName,
} from "../../../utils/parseWriteTodos";
import MessageBubble, { ToolDetailsInline } from "./MessageBubble";
import { PluginSurfaceSlot } from "../../../plugins/surfaces";
import { ToolMediaStrip } from "./ToolMediaStrip";
import { collectTurnToolMedia } from "../../../utils/collectTurnToolMedia";
import { collectTurnKnowledgeCitations } from "../../../utils/collectTurnKnowledgeCitations";
import { KnowledgeCitationsStrip } from "./KnowledgeCitationsStrip";
import { messageSpeakerId } from "../utils/messageGrouping";
import { isAssistantProcessLive } from "./liveAssistantTurn";
import {
  buildTurnBlocks,
  planTurnBlocks,
  type PlannedTurnBlock,
} from "../utils/turnBlocks";
import { ProcessStepGroup } from "./TurnProcessSteps";
import { isPinnedToolUiMessage } from "../../../plugins/toolRenderers/isPinnedToolUi";
import { useToolRendererVersion } from "../../../plugins/toolRenderers";
import styles from "../index.module.less";

interface AssistantTurnViewProps {
  messages: ChatMessage[];
  agentId?: string | null;
  /** Passed to ``conversation.view`` plugin surfaces. */
  threadId?: string | null;
  isStreaming?: boolean;
  /** True while this assistant turn is still being generated (incl. between tool calls). */
  isTurnInProgress?: boolean;
  /** This group sits after the latest user message, even if the session flag is idle. */
  afterLatestUser?: boolean;
  /**
   * Speakers still generating in the session store (survives tool gaps after
   * the composer unlocks). Empty string = unlabeled host.
   */
  liveSpeakers?: ReadonlyArray<string>;
  onRegenerate?: (messageId: string) => void;
  onDisableStreamUsage?: () => Promise<boolean>;
  onEditUserMessage?: (messageId: string, newText: string) => void;
  onForkAssistantMessage?: (messageId: string) => void;
  forkDisabled?: boolean;
  forkDisabledHint?: string;
  onAcpPermissionSelect?: (message: string) => void;
  onHitlDecision?: HitlDecisionHandler;
  onOpenBrowser?: () => void;
  onEditFile?: () => void;
  onRunShellCommand?: (code: string) => void;
  shellCommandDisabled?: boolean;
  shellCommandDisabledTitle?: string;
  /**
   * Surfaces that already render their own action timeline (Solo's activity
   * feed) set this to hide the chat-side thinking/tool steps and avoid showing
   * the same actions twice. Text, approval cards and rich tool UIs stay.
   * Defaults to false: full interleaved steps.
   */
  compactProcess?: boolean;
}

/** True when any message in this turn belongs to a still-live speaker. */
function turnHasLiveSpeaker(
  messages: ChatMessage[],
  liveSpeakers: ReadonlyArray<string>,
): boolean {
  if (liveSpeakers.length === 0) return false;
  const live = new Set(liveSpeakers);
  for (const message of messages) {
    if (live.has(messageSpeakerId(message))) return true;
  }
  return false;
}

/** A lone decision stamp would paint one row, then jump into the steps. */
function isLoneDecision(block: PlannedTurnBlock): boolean {
  return (
    block.kind === "process" &&
    block.steps.length > 0 &&
    block.steps.every((step) => step.kind === "decision")
  );
}

export default function AssistantTurnView({
  messages,
  agentId: agentIdProp,
  threadId = null,
  isTurnInProgress = false,
  afterLatestUser = false,
  liveSpeakers = [],
  onRegenerate,
  onDisableStreamUsage,
  onEditUserMessage,
  onForkAssistantMessage,
  forkDisabled,
  forkDisabledHint,
  onAcpPermissionSelect,
  onHitlDecision,
  onOpenBrowser,
  onEditFile,
  onRunShellCommand,
  shellCommandDisabled,
  shellCommandDisabledTitle,
  compactProcess = false,
}: AssistantTurnViewProps) {
  const { t } = useTranslation();
  const { activeAgentId } = useAgent();
  const agentId = agentIdProp ?? activeAgentId;
  const speakerAgentId =
    messages.map((item) => messageSpeakerId(item)).find(Boolean) || agentId;

  const speakerLive = turnHasLiveSpeaker(messages, liveSpeakers);
  const hasStreamingMsg = messages.some((m) => m.status === "streaming");
  const turnStreaming = isAssistantProcessLive({
    isTurnInProgress,
    afterLatestUser,
    hasStreamingMessage: hasStreamingMsg,
    speakerLive,
  });
  const hasPendingHitl = messages.some((m) => m.hitlData?.status === "pending");

  const splitOpts = useMemo(
    () => ({ joinAnswerFragments: turnStreaming }),
    [turnStreaming],
  );

  const fullSplit = useMemo(
    () => splitAssistantTurn(messages, splitOpts),
    [messages, splitOpts],
  );

  const toolMedia = useMemo(
    () => collectTurnToolMedia(fullSplit, speakerAgentId),
    [fullSplit, speakerAgentId],
  );
  const knowledgeCitations = useMemo(
    () => collectTurnKnowledgeCitations(fullSplit),
    [fullSplit],
  );

  const usedBrowser = turnUsedBrowserTool(fullSplit);
  const showOpenBrowser = usedBrowser && !!onOpenBrowser;
  const usedFileTool = turnUsedFileTool(fullSplit);
  const showEditFile = usedFileTool && !!onEditFile;
  const turnFileCount = useMemo(() => {
    const fromPaths = collectChatFilePaths(messages, agentId).length;
    if (fromPaths > 0) return fromPaths;
    return (fullSplit.tools ?? []).filter((msg) =>
      isWriteToolName(msg.toolData?.name),
    ).length;
  }, [messages, agentId, fullSplit.tools]);
  const hasToolMedia =
    toolMedia.images.length > 0 ||
    toolMedia.videos.length > 0 ||
    toolMedia.files.length > 0;

  const todoItems = useMemo(
    () => collectWriteTodosFromMessages(messages),
    [messages],
  );
  const todoStreaming =
    turnStreaming &&
    messages.some(
      (m) => m.status === "streaming" && isWriteTodosToolName(m.toolData?.name),
    );

  // Rich plugin UIs load async after mount — bump forces a rebuild.
  const rendererVersion = useToolRendererVersion();
  const blocks = useMemo(
    () =>
      planTurnBlocks(
        buildTurnBlocks(messages, { isPinnedTool: isPinnedToolUiMessage }),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rendererVersion invalidates pinned-tool lookups
    [messages, rendererVersion],
  );

  const deferLoneDecision = turnStreaming && !hasPendingHitl;
  const visibleBlocks = useMemo(() => {
    let next = compactProcess
      ? blocks.filter((block) => block.kind !== "process")
      : blocks;
    if (deferLoneDecision)
      next = next.filter((block) => !isLoneDecision(block));
    return next;
  }, [blocks, compactProcess, deferLoneDecision]);

  const avatarBlockId = useMemo(() => {
    const first = visibleBlocks.find(
      (block) =>
        block.kind === "text" ||
        block.kind === "process" ||
        block.kind === "error",
    );
    return first?.id ?? null;
  }, [visibleBlocks]);
  const lastTextBlockId = useMemo(() => {
    for (let i = visibleBlocks.length - 1; i >= 0; i -= 1) {
      if (visibleBlocks[i].kind === "text") return visibleBlocks[i].id;
    }
    return null;
  }, [visibleBlocks]);
  const firstProcessId = useMemo(() => {
    const first = visibleBlocks.find((block) => block.kind === "process");
    return first?.id ?? null;
  }, [visibleBlocks]);

  const todoPanel =
    todoItems.length > 0 ? (
      <TodoProgressPanel
        items={todoItems}
        isStreaming={todoStreaming}
        followingProcessSummary={Boolean(firstProcessId)}
      />
    ) : null;
  const todoAtTop = todoPanel && !firstProcessId ? todoPanel : null;

  const isWrapupTurn = messages.some((item) => item.teamWrapup);
  const hasVisibleTurn =
    visibleBlocks.length > 0 ||
    hasToolMedia ||
    knowledgeCitations.length > 0 ||
    showOpenBrowser ||
    showEditFile;
  // A decision-only placeholder has no row yet. Rendering an empty turn
  // would shift the layout before the avatar and the first status settle.
  if (!hasVisibleTurn) return null;

  const renderBlock = (block: PlannedTurnBlock, index: number) => {
    if (block.kind === "text") {
      const isFirst = index === 0;
      const isMetaOwner = block.id === lastTextBlockId;
      const groupPosition =
        isFirst && isMetaOwner
          ? "only"
          : isFirst
          ? "first"
          : isMetaOwner
          ? "last"
          : "middle";
      return (
        <div key={block.id} className={styles.assistantTurnAnswer}>
          <MessageBubble
            message={block.message}
            agentId={agentId}
            showAvatar={isFirst && block.id === avatarBlockId}
            groupPosition={groupPosition}
            onRegenerate={onRegenerate}
            onDisableStreamUsage={onDisableStreamUsage}
            onEditUserMessage={onEditUserMessage}
            onForkAssistantMessage={onForkAssistantMessage}
            forkDisabled={forkDisabled}
            forkDisabledHint={forkDisabledHint}
            onRunShellCommand={onRunShellCommand}
            shellCommandDisabled={shellCommandDisabled}
            shellCommandDisabledTitle={shellCommandDisabledTitle}
          />
          <PluginSurfaceSlot
            slot="conversation.view"
            context={{
              agentId,
              threadId,
              message: {
                id: block.message.id,
                role: block.message.role,
                content: block.message.content,
                createdAt: block.message.timestamp,
              },
            }}
          />
        </div>
      );
    }
    if (block.kind === "error") {
      return (
        <div key={block.id} className={styles.assistantTurnAnswer}>
          <MessageBubble
            message={block.message}
            agentId={agentId}
            showAvatar={block.id === avatarBlockId}
            groupPosition="only"
            onRegenerate={onRegenerate}
            onDisableStreamUsage={onDisableStreamUsage}
            onEditUserMessage={onEditUserMessage}
            onForkAssistantMessage={onForkAssistantMessage}
            forkDisabled={forkDisabled}
            forkDisabledHint={forkDisabledHint}
            onRunShellCommand={onRunShellCommand}
            shellCommandDisabled={shellCommandDisabled}
            shellCommandDisabledTitle={shellCommandDisabledTitle}
          />
          <PluginSurfaceSlot
            slot="conversation.view"
            context={{
              agentId,
              threadId,
              message: {
                id: block.message.id,
                role: block.message.role,
                content: block.message.content,
                createdAt: block.message.timestamp,
              },
            }}
          />
        </div>
      );
    }
    if (block.kind === "hitl") {
      return (
        <MessageBubble
          key={block.id}
          message={block.message}
          agentId={agentId}
          onHitlDecision={onHitlDecision}
          groupPosition="only"
        />
      );
    }
    if (block.kind === "toolCard") {
      if (!block.message.toolData) return null;
      return (
        <div key={block.id} className={styles.turnInset}>
          <div className={styles.pinnedToolResults} data-octop-pinned-tools="">
            <div className={styles.pinnedToolResultItem}>
              <ToolDetailsInline
                toolData={block.message.toolData}
                isStreaming={
                  block.message.status === "streaming" && turnStreaming
                }
                onAcpPermissionSelect={onAcpPermissionSelect}
                hideMediaPreview={hasToolMedia}
                agentId={speakerAgentId}
                forceError={block.message.status === "error"}
              />
            </div>
          </div>
        </div>
      );
    }
    return (
      <Fragment key={block.id}>
        <ProcessStepGroup
          steps={block.steps}
          merged={block.merged}
          durationMs={block.durationMs}
          failedCount={block.failedCount}
          isStreaming={turnStreaming && !hasPendingHitl}
          onAcpPermissionSelect={onAcpPermissionSelect}
          hideToolMedia={hasToolMedia}
          agentId={speakerAgentId}
          showAvatar={block.id === avatarBlockId}
        />
        {todoPanel && block.id === firstProcessId ? (
          <div className={styles.turnInset}>{todoPanel}</div>
        ) : null}
      </Fragment>
    );
  };

  const body = (
    <>
      {todoAtTop ? <div className={styles.turnInset}>{todoAtTop}</div> : null}
      {visibleBlocks.map(renderBlock)}
      {hasToolMedia && (
        <div className={styles.turnInset}>
          <ToolMediaStrip
            images={toolMedia.images}
            videos={toolMedia.videos}
            files={toolMedia.files}
            agentId={speakerAgentId}
          />
        </div>
      )}
      {knowledgeCitations.length > 0 ? (
        <div className={styles.turnInset}>
          <KnowledgeCitationsStrip citations={knowledgeCitations} />
        </div>
      ) : null}
      {showOpenBrowser && (
        <div className={styles.turnInset}>
          <button
            type="button"
            className={cx(
              styles.openBrowserPrompt,
              turnStreaming && styles.openBrowserPromptActive,
            )}
            onClick={onOpenBrowser}
            aria-label={t("chat.openBrowser")}
          >
            <Globe
              size={16}
              strokeWidth={2}
              className={styles.openBrowserPromptIcon}
              aria-hidden="true"
            />
            <span>{t("chat.openBrowser")}</span>
            <ChevronRight
              size={14}
              className={styles.openBrowserPromptArrow}
              aria-hidden="true"
            />
          </button>
        </div>
      )}
      {showEditFile && (
        <div className={styles.turnInset}>
          <button
            type="button"
            className={cx(
              styles.openBrowserPrompt,
              turnStreaming && styles.openBrowserPromptActive,
            )}
            onClick={onEditFile}
            aria-label={t("chat.editFileCard", {
              count: Math.max(turnFileCount, 1),
              defaultValue: "编辑了{{count}}个文件",
            })}
          >
            <FilePen
              size={16}
              strokeWidth={2}
              className={styles.openBrowserPromptIcon}
              aria-hidden="true"
            />
            <span>
              {t("chat.editFileCard", {
                count: Math.max(turnFileCount, 1),
                defaultValue: "编辑了{{count}}个文件",
              })}
            </span>
            <ChevronRight
              size={14}
              className={styles.openBrowserPromptArrow}
              aria-hidden="true"
            />
          </button>
        </div>
      )}
    </>
  );

  return (
    <div
      className={cx(
        styles.assistantTurn,
        compactProcess && styles.assistantTurnCompact,
      )}
    >
      {isWrapupTurn ? (
        <div className={styles.teamWrapupTurn}>
          <span className={styles.teamWrapupBadge}>
            {t("chat.teamWrapupBadge", { defaultValue: "主持人总结" })}
          </span>
          {body}
        </div>
      ) : (
        body
      )}
    </div>
  );
}
