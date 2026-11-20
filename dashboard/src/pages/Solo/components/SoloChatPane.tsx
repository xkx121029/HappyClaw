import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Spin } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { Check, ChevronDown, CircleAlert, Cpu, Sparkles } from "lucide-react";
import type { OctopAgent } from "../../../context/AgentContext";
import { message } from "@/utils/antdMessage";
import { useSkills } from "../../Agent/Skills/useSkills";
import { useChat } from "../../Chat/hooks/useChat";
import { useChatComposerResources } from "../../Chat/hooks/useChatComposerResources";
import * as chatStore from "../../Chat/hooks/chatStore";
import type { Session } from "../../Chat/hooks/useSessions";
import {
  buildComposerContext,
  resolveTurnModelRef,
} from "../../Chat/utils/chatMessages";
import {
  mergeAllowTools,
  type HitlSessionPolicy,
} from "../../Chat/utils/hitlSessionPolicy";
import {
  findAutoResumableApproval,
  findPendingAsk,
} from "../../Chat/utils/pendingHitl";
import { parseSkillSlugsInText } from "../../Chat/utils/skillSlash";
import MessageList from "../../Chat/components/MessageList";
import ChatInput from "../../Chat/components/ChatInput";
import AskQuestionCard from "../../Chat/components/AskQuestionCard";
import type { ChatAttachment } from "../../Chat/hooks/useChat";
import {
  modelOptionLabel,
  modelOptionValue,
  modelRefLabel,
} from "../../../utils/modelOptions";
import SoloMenu from "./SoloMenu";
import styles from "../solo.module.less";

interface SoloChatPaneProps {
  agentId: string | null;
  activeAgent: OctopAgent | null;
  agentReady: boolean;
  threadId: string | null;
  onSelectThread: (threadId: string | null) => void;
  /** 复用 SOLO 页顶层的 useSessions，避免两处重复拉会话列表。 */
  createSession: () => { session: Session; resolvedId: Promise<string> };
  /** 页级 useChat，供中间栏活动流共享同一份消息。 */
  chat: ReturnType<typeof useChat>;
  /** 页级 composer，模型快切与输入框共享同一份选择。 */
  composer: ReturnType<typeof useChatComposerResources>;
}

/**
 * SOLO 自己的对话面板：消息 + 输入框。
 *
 * 不依赖主界面侧栏，也不读全局 activeAgent；专家、模型都由 SOLO 页传入，
 * 因此和主模式的选中状态互不影响。
 */
export default function SoloChatPane({
  agentId,
  activeAgent,
  agentReady,
  threadId,
  onSelectThread,
  createSession,
  chat,
  composer,
}: SoloChatPaneProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const {
    messages,
    isStreaming,
    thinkingStartedAt,
    liveSpeakers,
    sendMessage,
    cancelStream,
  } = chat;
  const { skills } = useSkills(agentId, { enabled: agentReady });

  const [creatingThread, setCreatingThread] = useState(false);
  const creatingRef = useRef(false);

  const handleSend = useCallback(
    (text: string, attachments?: ChatAttachment[]) => {
      const trimmed = text.trim();
      if (!trimmed && !(attachments && attachments.length > 0)) return;
      if (!agentId) {
        message.warning(t("solo.pickAgentFirst"));
        return;
      }
      if (isStreaming) return;

      const composerContext = buildComposerContext({
        skills: parseSkillSlugsInText(trimmed),
        connectors: composer.selectedConnectors,
        knowledgeBaseIds: composer.selectedKnowledgeBaseIds,
        targetAgents: [],
        selectedModel: composer.selectedModel,
        reasoningMode: composer.reasoningMode,
        reasoningEffort: composer.reasoningEffort,
      });
      const modelRef = resolveTurnModelRef(
        composer.selectedModel,
        activeAgent?.default_model ?? null,
      );

      const dispatch = (targetThreadId: string) => {
        sendMessage(
          trimmed,
          "",
          agentId,
          attachments,
          targetThreadId,
          modelRef,
          composer.selectedConnectors,
          composer.selectedKnowledgeBaseIds,
          [],
          composerContext,
          composer.reasoningMode,
          composer.reasoningEffort,
          composer.conversationMode,
          composer.hitlPolicy,
        );
      };

      if (threadId) {
        dispatch(threadId);
        return;
      }

      // 首条消息：先落一个真实会话，避免 SOLO 页与 /chat 的路由跳转耦合。
      if (creatingRef.current) return;
      creatingRef.current = true;
      setCreatingThread(true);
      const { resolvedId } = createSession();
      void resolvedId
        .then((newThreadId) => {
          if (!newThreadId) {
            message.error(t("solo.createSessionFailed"));
            return;
          }
          onSelectThread(newThreadId);
          dispatch(newThreadId);
        })
        .finally(() => {
          creatingRef.current = false;
          setCreatingThread(false);
        });
    },
    [
      agentId,
      activeAgent?.default_model,
      composer,
      createSession,
      isStreaming,
      onSelectThread,
      sendMessage,
      t,
      threadId,
    ],
  );

  const composerDisabledReason = useMemo(() => {
    if (!agentId) return t("solo.noAgentHint");
    if (!agentReady) return t("solo.agentStoppedHint");
    return null;
  }, [agentId, agentReady, t]);

  // 长任务在等待批准 / 追问时会挂起；SOLO 必须能把决定回传，否则任务永远停在那里。
  const pendingAsk = useMemo(() => findPendingAsk(messages), [messages]);
  const autoResumedApprovalRef = useRef<string | null>(null);

  const handleHitlDecision = useCallback(
    (
      decisions: Array<{ type: string; message?: string }>,
      policy?: HitlSessionPolicy,
      pendingId?: string,
    ) => {
      const storeKey = threadId ?? undefined;
      if (policy) {
        const next =
          policy.mode === "allow_tools"
            ? mergeAllowTools(composer.hitlPolicy, policy.tools ?? [])
            : policy;
        const pending = findAutoResumableApproval(next, messages);
        if (pending && threadId) {
          autoResumedApprovalRef.current = `${threadId}:${pending.messageId}`;
        }
        composer.handleHitlPolicyChange(next, { persist: false });
        chat.resumeHitl(
          decisions,
          storeKey,
          undefined,
          next,
          pendingId ?? pending?.pendingId,
        );
        return;
      }
      chat.resumeHitl(decisions, storeKey, undefined, undefined, pendingId);
    },
    [chat, composer, messages, threadId],
  );

  const handleAskDismiss = useCallback(
    (actions: unknown[]) => {
      chat.resumeHitl(
        actions.map(() => ({
          type: "respond",
          message: t("chat.ask.dismissMessage"),
        })),
        threadId ?? undefined,
        true,
      );
    },
    [chat, t, threadId],
  );

  // 会话策略允许时自动放行迟到的审批投影，和主对话保持一致。
  useEffect(() => {
    if (isStreaming || !threadId) return;
    const policy = composer.hitlPolicy;
    const timer = window.setTimeout(() => {
      const pending = findAutoResumableApproval(
        policy,
        chatStore.getSnapshot(threadId).messages,
      );
      if (!pending?.pendingId) {
        autoResumedApprovalRef.current = null;
        return;
      }
      const resumeKey = `${threadId}:${pending.messageId}`;
      if (autoResumedApprovalRef.current === resumeKey) return;
      autoResumedApprovalRef.current = resumeKey;
      chat.resumeHitl(
        pending.actions.map(() => ({ type: "approve" })),
        threadId,
        undefined,
        policy,
        pending.pendingId,
      );
    }, 50);
    return () => window.clearTimeout(timer);
  }, [chat, composer.hitlPolicy, isStreaming, threadId, messages]);

  const showEmptyIntro = !threadId && messages.length === 0;
  // 从主对话回来 / 刚刷新时历史还在路上，先给明确反馈而不是空面板。
  const showHistoryLoading =
    Boolean(threadId) && messages.length === 0 && chat.historyLoading;

  // 模型入口是页面上唯一的模型切换点，宽度再窄也要能打开。
  const selectedLabel =
    modelRefLabel(composer.selectedModel ?? "", composer.availableModels) ||
    t("solo.autoModel");
  const modelMenuItems = [
    { key: "", label: t("solo.autoModel") },
    ...composer.availableModels.map((m) => ({
      key: modelOptionValue(m),
      label: modelOptionLabel(m),
    })),
    ...(composer.availableModels.length === 0
      ? [
          { type: "separator" as const },
          { key: "__config", label: t("solo.configureModels") },
        ]
      : []),
  ];

  const handleModelSelect = (key: string) => {
    setModelMenuOpen(false);
    if (key === "__config") {
      navigate("/admin/models");
      return;
    }
    composer.setSelectedModel(key || null);
  };

  return (
    <section className={styles.chatPane}>
      {composerDisabledReason ? (
        <div className={styles.noticeBlock}>
          <CircleAlert size={16} />
          <span>{composerDisabledReason}</span>
          <Link to="/experts">
            <Button size="small" type="link">
              {t("solo.goExperts")}
            </Button>
          </Link>
        </div>
      ) : null}

      <div className={styles.chatBody}>
        {showEmptyIntro ? (
          <div className={styles.welcome}>
            <div className={styles.welcomeCard}>
              <Sparkles size={18} />
            </div>
            <p className={styles.welcomeTitle}>{t("solo.introTitle")}</p>
            <p className={styles.welcomeSub}>{t("solo.introBody")}</p>
            <div className={styles.introList}>
              <div className={styles.introItem}>
                <Check size={13} />
                <span>{t("solo.introFiles")}</span>
              </div>
              <div className={styles.introItem}>
                <Check size={13} />
                <span>{t("solo.introTerminal")}</span>
              </div>
              <div className={styles.introItem}>
                <Check size={13} />
                <span>{t("solo.introBrowser")}</span>
              </div>
            </div>
          </div>
        ) : showHistoryLoading ? (
          <div className={styles.chatLoading}>
            <Spin size="small" />
            <span>{t("solo.loadingThread")}</span>
          </div>
        ) : (
          <MessageList
            messages={messages}
            agentId={agentId}
            isStreaming={isStreaming}
            thinkingStartedAt={thinkingStartedAt}
            liveSpeakers={liveSpeakers}
            sessionKey={threadId ?? undefined}
            compactProcess
            onHitlDecision={handleHitlDecision}
            onAcpPermissionSelect={(permissionMessage) =>
              handleSend(permissionMessage)
            }
          />
        )}
      </div>

      {pendingAsk ? (
        <div className={styles.askQuestionDock}>
          <div className={styles.askQuestionDockInner}>
            <AskQuestionCard
              key={pendingAsk.messageId}
              questions={pendingAsk.questions}
              status="pending"
              docked
              onSubmit={(answer) =>
                handleHitlDecision(
                  pendingAsk.actions.map(() => ({
                    type: "respond",
                    message: answer,
                  })),
                )
              }
              onDismiss={() => handleAskDismiss(pendingAsk.actions)}
            />
          </div>
        </div>
      ) : null}

      <div className={styles.chatComposer}>
        <ChatInput
          agentId={agentId}
          threadId={threadId}
          onSend={handleSend}
          onCancel={cancelStream}
          onNewChat={() => onSelectThread(null)}
          isStreaming={isStreaming}
          disabled={Boolean(composerDisabledReason) || creatingThread}
          availableModels={composer.availableModels}
          selectedModel={composer.selectedModel}
          onModelChange={composer.setSelectedModel}
          reasoningMode={composer.reasoningMode}
          reasoningEffort={composer.reasoningEffort}
          onReasoningChange={composer.handleReasoningChange}
          conversationMode={composer.conversationMode}
          onConversationModeChange={composer.handleConversationModeChange}
          hitlPolicy={composer.hitlPolicy}
          onHitlPolicyChange={composer.handleHitlPolicyChange}
          availableConnectors={composer.chatConnectors}
          selectedConnectors={composer.selectedConnectors}
          onConnectorsChange={composer.handleConnectorsChange}
          availableKnowledgeBases={composer.chatKnowledgeBases}
          selectedKnowledgeBaseIds={composer.selectedKnowledgeBaseIds}
          onKnowledgeBaseIdsChange={composer.handleKnowledgeBaseIdsChange}
          availableSkills={skills}
          defaultModel={activeAgent?.default_model ?? null}
        />
        <div className={styles.menuAnchor}>
          <button
            type="button"
            className={styles.composerModel}
            data-testid="composer-model-chip"
            title={t("solo.pickModel")}
            onClick={() => setModelMenuOpen((v) => !v)}
          >
            <Cpu size={12} />
            <span className={styles.composerModelLabel}>{selectedLabel}</span>
            <ChevronDown size={10} />
          </button>
          {modelMenuOpen ? (
            <SoloMenu
              className={styles.modelMenu}
              items={modelMenuItems}
              onSelect={handleModelSelect}
              onClose={() => setModelMenuOpen(false)}
            />
          ) : null}
        </div>
      </div>
    </section>
  );
}
