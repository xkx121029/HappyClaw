import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { Link } from "react-router-dom";
import { CircleAlert, Sparkles } from "lucide-react";
import cx from "classnames";
import { useAgent } from "../../../context/AgentContext";
import { message } from "@/utils/antdMessage";
import { isAgentChatReady } from "../../../utils/agentError";
import { useSkills } from "../../Agent/Skills/useSkills";
import { useChat } from "../../Chat/hooks/useChat";
import { useChatComposerResources } from "../../Chat/hooks/useChatComposerResources";
import type { Session } from "../../Chat/hooks/useSessions";
import {
  buildComposerContext,
  resolveTurnModelRef,
} from "../../Chat/utils/chatMessages";
import { parseSkillSlugsInText } from "../../Chat/utils/skillSlash";
import MessageList from "../../Chat/components/MessageList";
import ChatInput from "../../Chat/components/ChatInput";
import type { ChatAttachment } from "../../Chat/hooks/useChat";
import styles from "../solo.module.less";

interface SoloChatPaneProps {
  agentId: string | null;
  threadId: string | null;
  onSelectThread: (threadId: string | null) => void;
  /** 复用 SOLO 页顶层的 useSessions，避免两处重复拉会话列表。 */
  createSession: () => { session: Session; resolvedId: Promise<string> };
}

export default function SoloChatPane({
  agentId,
  threadId,
  onSelectThread,
  createSession,
}: SoloChatPaneProps) {
  const { t } = useTranslation();
  const { activeAgent } = useAgent();
  const agentReady = isAgentChatReady(activeAgent?.state, activeAgent);

  const { messages, isStreaming, thinkingStartedAt, liveSpeakers, sendMessage, cancelStream } =
    useChat(threadId, agentId, false);
  const { skills } = useSkills(agentId, { enabled: agentReady });

  const composer = useChatComposerResources(agentId, threadId);
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

  const showEmptyIntro = !threadId && messages.length === 0;

  return (
    <section className={styles.chatPane}>
      <header className={styles.paneHeader}>
        <span
          className={cx(
            styles.statusDot,
            agentReady ? styles.statusDotOn : styles.statusDotOff,
          )}
        />
        <span className={styles.paneTitle}>
          {activeAgent?.name ?? t("solo.noAgent")}
        </span>
        <span className={styles.paneBadge}>SOLO</span>
      </header>

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
          <div className={styles.chatIntro}>
            <Sparkles size={18} />
            <p className={styles.chatIntroTitle}>{t("solo.introTitle")}</p>
            <p className={styles.chatIntroText}>{t("solo.introBody")}</p>
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
          />
        )}
      </div>

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
      </div>
    </section>
  );
}
