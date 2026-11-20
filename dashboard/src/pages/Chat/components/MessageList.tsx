import {
  forwardRef,
  useEffect,
  useRef,
  useCallback,
  useMemo,
  useState,
  useLayoutEffect,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { Spin, Button } from "antd";
import { Virtuoso, type Components, type VirtuosoHandle } from "react-virtuoso";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import type { HitlDecisionHandler } from "../../../api/types/hitl";
import { useNewIds } from "../../../motion";
import type { ChatMessage } from "../hooks/useChat";
import type { ComposerTagLookups } from "./UserMessageComposerTags";
import MessageBubble from "./MessageBubble";
import AssistantTurnView from "./AssistantTurnView";
import { PluginSurfaceSlot } from "../../../plugins/surfaces";
import ScrollToBottomButton from "./ScrollToBottomButton";
import GeneratingIndicator from "./GeneratingIndicator";
import TurnTimelineRail from "./TurnTimelineRail";
import { isLiveAssistantTurn } from "./liveAssistantTurn";
import {
  awaitingVisibleAssistantReply,
  chatGeneratingPhase,
} from "./generatingGate";
import { useAutoScroll } from "../hooks/useAutoScroll";
import { findLastBrowserTurnGroupIndex } from "../utils/messageContent";
import {
  groupConsecutiveAssistantMessages,
  type MessageGroup,
} from "../utils/messageGrouping";
import { resolveLiveSpeakerNames } from "../utils/liveSpeakerLabel";
import { useAgent } from "../../../context/AgentContext";
import {
  nextCanLoadOlder,
  shouldAutoFillOlderHistory,
  shouldReleaseLoadMoreLatch,
} from "./loadOlderGate";
import { prependAnchorShift } from "../utils/prependAnchor";
import type { MessageSearchHit } from "../utils/messageSearch";
import {
  applySearchHighlights,
  clearSearchHighlights,
  findOccurrenceRect,
} from "../utils/chatSearchHighlights";
import * as chatStore from "../hooks/chatStore";
import { shouldBlockHistoryRefresh } from "../hooks/wsResumeGate";
import styles from "../index.module.less";

/** Virtualize long threads; short chats keep the simpler DOM path. */
const VIRTUALIZE_THRESHOLD = 30;

/** Virtuoso prepend anchor — count down when older pages are prepended. */
const VIRTUOSO_START_INDEX = 1_000_000;

interface VirtuosoListContext {
  historyHeader: ReactNode;
  footer: ReactNode;
}

type VirtuosoListProps = HTMLAttributes<HTMLDivElement> & {
  context?: VirtuosoListContext;
};

const VirtuosoList = forwardRef<HTMLDivElement, VirtuosoListProps>(
  function VirtuosoList(
    { style, children, className, context: _context, ...props },
    ref,
  ) {
    return (
      <div
        ref={ref}
        {...props}
        style={style}
        className={cx(styles.messageListInner, className)}
      >
        {children}
      </div>
    );
  },
);

/** Stable identity — avoid remounting Header/Footer on every parent render. */
const virtuosoComponents: Components<MessageGroup, VirtuosoListContext> = {
  List: VirtuosoList as Components<MessageGroup, VirtuosoListContext>["List"],
  Header: ({ context }) =>
    context?.historyHeader ? <div>{context.historyHeader}</div> : null,
  Footer: ({ context }) =>
    context?.footer ? <div>{context.footer}</div> : null,
};

interface MessageListProps {
  messages: ChatMessage[];
  agentId?: string | null;
  composerLookups?: ComposerTagLookups;
  loading?: boolean;
  historyHasMore?: boolean;
  historyLoadingMore?: boolean;
  historyRefreshing?: boolean;
  /** Return false when the load did not start (caller must release any latch). */
  onLoadMoreHistory?: () => boolean | void | Promise<boolean | void>;
  onRefreshHistory?: () => void;
  isStreaming?: boolean;
  /** Speakers still generating (tool gaps after composer unlock). */
  liveSpeakers?: ReadonlyArray<string>;
  thinkingStartedAt?: number | null;
  sessionKey?: string;
  onRegenerate?: (messageId: string) => void;
  onDisableStreamUsage?: () => Promise<boolean>;
  onEditUserMessage?: (messageId: string, newText: string) => void;
  onWithdrawSteer?: (messageId: string) => void;
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
  compactProcess?: boolean;
  /** Notify chat chrome when the in-thread turn rail is shown (for gutter align). */
  onTurnRailVisibilityChange?: (visible: boolean) => void;
  /** 会话内搜索的查询词；虚拟列表只高亮已渲染的行。 */
  searchQuery?: string;
  /** 当前命中，驱动定位滚动。 */
  searchHit?: MessageSearchHit | null;
  /** 搜索条展开时记录滚动位置，关闭后还原。 */
  searchOpen?: boolean;
}

interface GroupRenderContext {
  agentId?: string | null;
  /** Thread id for ``conversation.view`` plugin surfaces. */
  threadId?: string | null;
  composerLookups?: ComposerTagLookups;
  isStreaming?: boolean;
  liveSpeakers?: ReadonlyArray<string>;
  lastBrowserGroupIndex: number;
  lastAssistantGroupIndex: number;
  lastUserGroupIndex: number;
  onRegenerate?: (messageId: string) => void;
  onDisableStreamUsage?: () => Promise<boolean>;
  onEditUserMessage?: (messageId: string, newText: string) => void;
  onWithdrawSteer?: (messageId: string) => void;
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
  compactProcess?: boolean;
  registerBubbleRef: (messageId: string, el: HTMLDivElement | null) => void;
  /** 刚出现、需要播放入场动效的消息组（历史与重连不播）。 */
  freshGroupKeys: ReadonlySet<string>;
}

function renderMessageGroup(
  group: MessageGroup,
  groupIndex: number,
  ctx: GroupRenderContext,
) {
  const openBrowserHandler =
    ctx.onOpenBrowser && groupIndex === ctx.lastBrowserGroupIndex
      ? ctx.onOpenBrowser
      : undefined;
  const afterLatestUser = groupIndex > ctx.lastUserGroupIndex;
  const groupKey = group.messages[0]?.id ?? `g-${groupIndex}`;
  const enterProps = ctx.freshGroupKeys.has(groupKey)
    ? ({
        className: "octop-enter",
        "data-motion": "rise",
        "data-motion-duration": "fast",
      } as const)
    : {};
  const isTurnInProgress = isLiveAssistantTurn({
    isStreaming: Boolean(ctx.isStreaming),
    groupIndex,
    lastAssistantGroupIndex: ctx.lastAssistantGroupIndex,
    lastUserGroupIndex: ctx.lastUserGroupIndex,
  });

  if (!group.isGroup || group.messages.length === 1) {
    const msg = group.messages[0];
    if (msg.role === "assistant") {
      return (
        <div
          data-message-id={msg.id}
          data-role="assistant"
          {...enterProps}
          ref={(el) => {
            ctx.registerBubbleRef(msg.id, el);
          }}
        >
          <AssistantTurnView
            messages={[msg]}
            agentId={ctx.agentId}
            threadId={ctx.threadId}
            isTurnInProgress={isTurnInProgress}
            afterLatestUser={afterLatestUser}
            liveSpeakers={ctx.liveSpeakers}
            onRegenerate={ctx.onRegenerate}
            onDisableStreamUsage={ctx.onDisableStreamUsage}
            onEditUserMessage={ctx.onEditUserMessage}
            onForkAssistantMessage={ctx.onForkAssistantMessage}
            forkDisabled={ctx.forkDisabled}
            forkDisabledHint={ctx.forkDisabledHint}
            onAcpPermissionSelect={ctx.onAcpPermissionSelect}
            onHitlDecision={ctx.onHitlDecision}
            onOpenBrowser={openBrowserHandler}
            onEditFile={ctx.onEditFile}
            onRunShellCommand={ctx.onRunShellCommand}
            shellCommandDisabled={ctx.shellCommandDisabled}
            shellCommandDisabledTitle={ctx.shellCommandDisabledTitle}
            compactProcess={ctx.compactProcess}
          />
        </div>
      );
    }
    return (
      <div
        data-message-id={msg.id}
        data-role={msg.role}
        {...enterProps}
        ref={(el) => {
          ctx.registerBubbleRef(msg.id, el);
        }}
      >
        <MessageBubble
          message={msg}
          agentId={ctx.agentId}
          composerLookups={ctx.composerLookups}
          onRegenerate={ctx.onRegenerate}
          onDisableStreamUsage={ctx.onDisableStreamUsage}
          onEditUserMessage={ctx.onEditUserMessage}
          onWithdrawSteer={ctx.onWithdrawSteer}
        />
        <PluginSurfaceSlot
          slot="conversation.view"
          context={{
            agentId: ctx.agentId,
            threadId: ctx.threadId,
            message: {
              id: msg.id,
              role: msg.role,
              content: msg.content,
              createdAt: msg.timestamp,
            },
          }}
        />
      </div>
    );
  }

  const groupKeyForRender = group.messages[0]?.id ?? "assistant-turn";
  return (
    <div
      key={groupKeyForRender}
      data-message-id={group.messages[0]?.id}
      data-role="assistant"
      {...enterProps}
      ref={(el) => {
        for (const msg of group.messages) {
          ctx.registerBubbleRef(msg.id, el);
        }
      }}
    >
      <AssistantTurnView
        messages={group.messages}
        agentId={ctx.agentId}
        threadId={ctx.threadId}
        isTurnInProgress={isTurnInProgress}
        afterLatestUser={afterLatestUser}
        liveSpeakers={ctx.liveSpeakers}
        onRegenerate={ctx.onRegenerate}
        onDisableStreamUsage={ctx.onDisableStreamUsage}
        onEditUserMessage={ctx.onEditUserMessage}
        onForkAssistantMessage={ctx.onForkAssistantMessage}
        forkDisabled={ctx.forkDisabled}
        forkDisabledHint={ctx.forkDisabledHint}
        onAcpPermissionSelect={ctx.onAcpPermissionSelect}
        onHitlDecision={ctx.onHitlDecision}
        onOpenBrowser={openBrowserHandler}
        onEditFile={ctx.onEditFile}
        onRunShellCommand={ctx.onRunShellCommand}
        shellCommandDisabled={ctx.shellCommandDisabled}
        shellCommandDisabledTitle={ctx.shellCommandDisabledTitle}
        compactProcess={ctx.compactProcess}
      />
    </div>
  );
}

export default function MessageList(props: MessageListProps) {
  const {
    messages,
    agentId,
    composerLookups,
    loading,
    historyHasMore,
    historyLoadingMore,
    historyRefreshing,
    onLoadMoreHistory,
    onRefreshHistory,
    isStreaming,
    liveSpeakers = [],
    thinkingStartedAt = null,
    sessionKey,
    onRegenerate,
    onDisableStreamUsage,
    onEditUserMessage,
    onWithdrawSteer,
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
    compactProcess,
    onTurnRailVisibilityChange,
    searchQuery = "",
    searchHit = null,
    searchOpen = false,
  } = props;

  const { t } = useTranslation();
  const { agents, activeAgent } = useAgent();
  const virtuosoRef = useRef<VirtuosoHandle | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const scrollerRef = useRef<HTMLElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const bubbleRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
  const prevInitialLoadingRef = useRef(false);
  const scrollHeightBeforePrependRef = useRef<number | null>(null);
  const loadMoreRequestedRef = useRef(false);
  const canLoadOlderRef = useRef(false);
  /** Virtuoso reports at-top separately — scrollTop is not near 0 with firstItemIndex. */
  const atTopRef = useRef(false);
  const lastSmoothScrolledUserIdRef = useRef<string | null>(null);
  const skipNextDepsScrollRef = useRef(false);
  const [scrollerMountKey, setScrollerMountKey] = useState(0);
  const [useVirtualLocked, setUseVirtualLocked] = useState(false);
  const [firstItemIndex, setFirstItemIndex] = useState(VIRTUOSO_START_INDEX);
  /** First group id when an older-page load starts. Appends must not count as prepends. */
  const prependAnchorIdRef = useRef<string | null>(null);

  const messageGroups = useMemo(
    () => groupConsecutiveAssistantMessages(messages, agentId ?? undefined),
    [messages, agentId],
  );
  const messageGroupsRef = useRef(messageGroups);
  messageGroupsRef.current = messageGroups;

  const useVirtual =
    useVirtualLocked || messageGroups.length >= VIRTUALIZE_THRESHOLD;

  const lastMsg = messages[messages.length - 1];
  const hasLiveSpeakers = liveSpeakers.length > 0;
  const awaitingVisibleReply = useMemo(
    () => awaitingVisibleAssistantReply(messages),
    [messages],
  );
  const {
    showFooter: showGenerating,
    showElapsed: isAwaitingAssistantReply,
    membersOnly: generatingMembersOnly,
  } = chatGeneratingPhase({
    isStreaming: Boolean(isStreaming),
    loading: Boolean(loading),
    lastMessageRole: lastMsg?.role,
    hasLiveSpeakers,
    awaitingVisibleReply,
  });
  const liveSpeakerNames = useMemo(
    () =>
      resolveLiveSpeakerNames(liveSpeakers, agents, {
        hostId: activeAgent?.agent_id,
        hostName: activeAgent?.name,
        limit: 2,
      }),
    [liveSpeakers, agents, activeAgent?.agent_id, activeAgent?.name],
  );

  const stableSessionKey = sessionKey || "__default__";

  // Keep this callback identity stable. An inline parent `onLoadMoreHistory`
  // (or flag churn) used to recreate it every render → useAutoScroll re-bound
  // scroll listeners and Virtuoso Header/Footer remounted, which broke the
  // "scroll up → load earlier" gesture in practice.
  const loadOlderGateRef = useRef({
    historyHasMore,
    historyLoadingMore,
    loading,
    onLoadMoreHistory,
    useVirtual,
  });
  loadOlderGateRef.current = {
    historyHasMore,
    historyLoadingMore,
    loading,
    onLoadMoreHistory,
    useVirtual,
  };

  const requestOlderMessages = useCallback(() => {
    const g = loadOlderGateRef.current;
    if (
      !canLoadOlderRef.current ||
      !g.historyHasMore ||
      g.historyLoadingMore ||
      g.loading ||
      !g.onLoadMoreHistory ||
      loadMoreRequestedRef.current
    ) {
      return;
    }
    const scroller = g.useVirtual ? scrollerRef.current : containerRef.current;
    if (scroller instanceof HTMLElement) {
      scrollHeightBeforePrependRef.current = scroller.scrollHeight;
    }
    const anchorGroup = messageGroupsRef.current[0];
    prependAnchorIdRef.current = anchorGroup?.messages[0]?.id ?? null;
    loadMoreRequestedRef.current = true;
    void Promise.resolve(g.onLoadMoreHistory()).then(
      (started) => {
        // Early-return in loadMoreHistory leaves historyLoadingMore false, so the
        // effect below never clears this latch — release it explicitly.
        if (shouldReleaseLoadMoreLatch(started)) {
          loadMoreRequestedRef.current = false;
          scrollHeightBeforePrependRef.current = null;
          prependAnchorIdRef.current = null;
        }
      },
      () => {
        loadMoreRequestedRef.current = false;
        scrollHeightBeforePrependRef.current = null;
        prependAnchorIdRef.current = null;
      },
    );
  }, []);

  // Keep the refresh trigger's identity stable so the scroll-listener effect
  // in useAutoScroll never re-mounts (which would reset its overscroll guard
  // and fire the refresh twice). Latest values are read from a ref.
  const refreshStateRef = useRef({
    historyRefreshing,
    loading,
    isStreaming,
    liveSpeakerCount: liveSpeakers.length,
    onRefreshHistory,
    hasMessages: messages.length > 0,
    sessionKey: stableSessionKey,
  });
  refreshStateRef.current = {
    historyRefreshing,
    loading,
    isStreaming,
    liveSpeakerCount: liveSpeakers.length,
    onRefreshHistory,
    hasMessages: messages.length > 0,
    sessionKey: stableSessionKey,
  };
  const refreshCooldownRef = useRef(0);

  const requestRefreshMessages = useCallback(() => {
    const s = refreshStateRef.current;
    const now = Date.now();
    const snap = chatStore.getSnapshot(s.sessionKey);
    if (
      s.historyRefreshing ||
      s.loading ||
      shouldBlockHistoryRefresh({
        isStreaming: Boolean(snap.isStreaming || s.isStreaming),
        hasLiveSocket: chatStore.hasLiveSocket(s.sessionKey),
        liveSpeakerCount: Math.max(
          snap.liveSpeakers.length,
          s.liveSpeakerCount,
        ),
        hasStreamingMessage: snap.messages.some(
          (message) => message.status === "streaming",
        ),
      }) ||
      !s.onRefreshHistory ||
      !s.hasMessages ||
      now - refreshCooldownRef.current < 3000
    ) {
      return;
    }
    refreshCooldownRef.current = now;
    s.onRefreshHistory();
  }, []);

  const virtualItemCountRef = useRef(messageGroups.length);
  virtualItemCountRef.current = messageGroups.length;
  const firstItemIndexRef = useRef(firstItemIndex);
  firstItemIndexRef.current = firstItemIndex;

  const virtualScrollConfig = useMemo(
    () =>
      useVirtual
        ? {
            virtuosoRef,
            scrollerRef,
            itemCountRef: virtualItemCountRef,
            firstItemIndexRef,
          }
        : null,
    [useVirtual],
  );

  // Fingerprint the in-progress assistant turn (not only the last message).
  // Thinking often lives on an earlier bubble while tools stream on later ones;
  // tool results grow in toolData without changing `content`.
  // Generating footer height is stable for the whole stream — omit from token.
  const scrollFollowToken = useMemo(() => {
    let token = `${messages.length}|${showGenerating ? 1 : 0}`;
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === "user") break;
      const blocksLen =
        m.contentBlocks?.reduce((n, b) => n + b.content.length, 0) ?? 0;
      const toolArgs = m.toolData?.arguments?.length ?? 0;
      const toolResult = m.toolData?.output?.length ?? 0;
      token += `|${m.id}:${m.status}:${m.content.length}:${blocksLen}:${toolArgs}:${toolResult}`;
    }
    return token;
  }, [messages, showGenerating]);

  const {
    showScrollBtn,
    scrollToBottom,
    armProgrammaticGuard,
    handleAtBottomChange,
  } = useAutoScroll({
    containerRef,
    endRef,
    virtual: virtualScrollConfig,
    scrollerMountKey,
    onNearTop: requestOlderMessages,
    // Virtuoso + firstItemIndex: at-top is not scrollTop≈0. Non-virtual omits
    // this so scrollTop near 0 still counts.
    ...(useVirtual ? { isAtTop: () => atTopRef.current } : {}),
    onOverscrollBottom: requestRefreshMessages,
    deps: [scrollFollowToken],
    skipNextDepsScrollRef,
    // 搜索打开时由搜索条接管视口，流式追加不再把视口拽回底部。
    followSuspended: searchOpen,
  });

  const handleAtTopStateChange = useCallback(
    (atTop: boolean) => {
      atTopRef.current = atTop;
      if (atTop) requestOlderMessages();
    },
    [requestOlderMessages],
  );
  useEffect(() => {
    if (!historyLoadingMore) {
      loadMoreRequestedRef.current = false;
      // Still parked at the top after a page lands — keep loading without a click.
      if (atTopRef.current) {
        requestOlderMessages();
      }
    }
  }, [historyLoadingMore, requestOlderMessages]);

  useLayoutEffect(() => {
    if (scrollHeightBeforePrependRef.current === null) return;

    const shift = prependAnchorShift(messageGroups, prependAnchorIdRef.current);
    const clearPrependGuard = () => {
      scrollHeightBeforePrependRef.current = null;
      prependAnchorIdRef.current = null;
    };
    const restoreScrollByHeight = () => {
      const scroller = useVirtual ? scrollerRef.current : containerRef.current;
      if (!(scroller instanceof HTMLElement)) return;
      const before = scrollHeightBeforePrependRef.current;
      if (before === null) return;
      armProgrammaticGuard();
      scroller.scrollTop += scroller.scrollHeight - before;
    };

    // A send while older history is loading grows the list at the bottom.
    // Shifting firstItemIndex by that delta opens a blank slot and the new
    // bubble never lands where the user is looking.
    if (shift.prependedGroups === 0 && !shift.mergedIntoFirst) {
      if (!historyLoadingMore) clearPrependGuard();
      return;
    }

    if (useVirtual && shift.prependedGroups > 0) {
      setFirstItemIndex((idx) => idx - shift.prependedGroups);
      clearPrependGuard();
      return;
    }

    // Non-virtual prepend, or older rows merged into the anchored group:
    // keep the viewport on the same messages by the height delta.
    restoreScrollByHeight();
    clearPrependGuard();
  }, [
    messages,
    messageGroups,
    useVirtual,
    historyLoadingMore,
    armProgrammaticGuard,
  ]);

  const historyHeader = useMemo(() => {
    if (!historyHasMore && !historyLoadingMore) return null;
    return (
      <div className={styles.turnInset}>
        <div className={styles.historyLoadMore}>
          {historyLoadingMore ? (
            <>
              <Spin size="small" />
              <span>{t("chat.loadingEarlierMessages")}</span>
            </>
          ) : (
            <>
              <span className={styles.historyLoadMoreHint}>
                {t("chat.scrollForEarlierMessages")}
              </span>
              <Button
                type="link"
                size="small"
                className={styles.historyLoadMoreBtn}
                onClick={requestOlderMessages}
              >
                {t("chat.loadEarlierMessages")}
              </Button>
            </>
          )}
        </div>
      </div>
    );
  }, [historyHasMore, historyLoadingMore, requestOlderMessages, t]);

  const refreshFooter = useMemo(() => {
    if (!historyRefreshing) return null;
    return (
      <div className={styles.turnInset}>
        <div className={styles.historyLoadMore}>
          <Spin size="small" />
          <span>{t("chat.refreshingMessages")}</span>
        </div>
      </div>
    );
  }, [historyRefreshing, t]);

  const lastBrowserGroupIndex = useMemo(
    () => findLastBrowserTurnGroupIndex(messageGroups),
    [messageGroups],
  );

  const lastAssistantGroupIndex = useMemo(() => {
    for (let i = messageGroups.length - 1; i >= 0; i--) {
      if (messageGroups[i].messages.some((m) => m.role === "assistant"))
        return i;
    }
    return -1;
  }, [messageGroups]);

  const lastUserGroupIndex = useMemo(() => {
    for (let i = messageGroups.length - 1; i >= 0; i--) {
      if (messageGroups[i].messages.some((m) => m.role === "user")) return i;
    }
    return -1;
  }, [messageGroups]);

  const registerBubbleRef = useCallback(
    (messageId: string, el: HTMLDivElement | null) => {
      if (el) bubbleRefsMap.current.set(messageId, el);
      else bubbleRefsMap.current.delete(messageId);
    },
    [],
  );

  // ---- 会话内搜索（Ctrl/Cmd + F）----
  const searchScrollTopRef = useRef<number | null>(null);
  // 定位时只读最新值：消息增长不应该把视口重新拽回命中处。
  const searchNavRef = useRef({ groups: messageGroups, firstItemIndex });
  searchNavRef.current = { groups: messageGroups, firstItemIndex };
  /** 分组渲染时 data-message-id 挂在首条消息上，命中后面几条时要换算到容器。 */
  const searchContainerId = useMemo(() => {
    if (!searchHit) return null;
    const group = messageGroups.find((item) =>
      item.messages.some((message) => message.id === searchHit.messageId),
    );
    return group?.messages[0]?.id ?? searchHit.messageId;
  }, [messageGroups, searchHit]);

  // 打开时记住滚动位置，关闭（Esc 或按钮）后原样还原。
  useEffect(() => {
    if (!searchOpen) return;
    const root = useVirtual ? scrollerRef.current : containerRef.current;
    if (root instanceof HTMLElement) {
      searchScrollTopRef.current = root.scrollTop;
    }
    return () => {
      const saved = searchScrollTopRef.current;
      searchScrollTopRef.current = null;
      const current = useVirtual ? scrollerRef.current : containerRef.current;
      if (saved === null || !(current instanceof HTMLElement)) return;
      armProgrammaticGuard(320);
      current.scrollTop = saved;
    };
  }, [searchOpen, useVirtual, armProgrammaticGuard]);

  const searchHitMessageId = searchHit?.messageId ?? null;
  const searchHitOccurrence = searchHit?.occurrence ?? -1;

  // 上下切换命中：先把消息滚进视口，再把第 n 处命中挪到中间。
  // 虚拟列表要先等目标行挂载，所以按帧重试几次，而不是只等一帧。
  useEffect(() => {
    if (!searchOpen || !searchHitMessageId) return;
    // 只依赖命中坐标：流式追加消息会让 searchHit 换新对象，
    // 那不该把视口重新拽回命中处。
    const messageId = searchHitMessageId;
    const occurrence = searchHitOccurrence;
    const { groups, firstItemIndex: startIndex } = searchNavRef.current;
    const groupIndex = groups.findIndex((group) =>
      group.messages.some((message) => message.id === messageId),
    );
    if (groupIndex < 0) return;

    const root = useVirtual ? scrollerRef.current : containerRef.current;
    let frame = 0;
    let attempts = 0;
    let cancelled = false;

    const centerOnHit = (): boolean => {
      if (!(root instanceof HTMLElement)) return true;
      const rect = findOccurrenceRect(
        root,
        searchQuery,
        searchContainerId,
        occurrence,
      );
      if (!rect) return false;
      const box = root.getBoundingClientRect();
      const delta = rect.top - box.top - box.height / 2 + rect.height / 2;
      if (Math.abs(delta) > 24) {
        armProgrammaticGuard(400);
        root.scrollTop += delta;
      }
      return true;
    };

    // 先把目标行交给列表定位；Virtuoso 会在下一帧挂载它。
    armProgrammaticGuard(400);
    if (useVirtual) {
      virtuosoRef.current?.scrollToIndex({
        index: startIndex + groupIndex,
        align: "center",
        behavior: "auto",
      });
    } else {
      bubbleRefsMap.current
        .get(searchContainerId ?? messageId)
        ?.scrollIntoView({ block: "center" });
    }

    const tick = () => {
      if (cancelled) return;
      attempts += 1;
      if (centerOnHit() || attempts >= 12) return;
      // Virtuoso 偶尔第一次测量落空，过半程再请求一次。
      if (useVirtual && attempts === 6) {
        virtuosoRef.current?.scrollToIndex({
          index: startIndex + groupIndex,
          align: "center",
          behavior: "auto",
        });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
    };
  }, [
    searchOpen,
    searchHitMessageId,
    searchHitOccurrence,
    searchQuery,
    searchContainerId,
    useVirtual,
    armProgrammaticGuard,
  ]);

  // 高亮：虚拟列表滚动会复用节点，所以每次滚动都重算一遍 Range。
  useEffect(() => {
    if (!searchOpen) {
      clearSearchHighlights();
      return;
    }
    const root = (
      useVirtual ? scrollerRef.current : containerRef.current
    ) as HTMLElement | null;
    if (!root || !searchQuery.trim()) {
      clearSearchHighlights();
      return;
    }
    let frame = 0;
    const paint = () => {
      frame = 0;
      applySearchHighlights(
        root,
        searchQuery,
        searchContainerId,
        searchHitOccurrence,
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(paint);
    };
    paint();
    root.addEventListener("scroll", schedule, { passive: true });
    // 虚拟列表滚动时新行是「挂载」而不是滚动触发的，光监听 scroll 会漏掉高亮。
    const observer = new MutationObserver(schedule);
    observer.observe(root, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      observer.disconnect();
      root.removeEventListener("scroll", schedule);
      clearSearchHighlights();
    };
  }, [
    searchOpen,
    searchQuery,
    searchHitOccurrence,
    searchContainerId,
    useVirtual,
    scrollerMountKey,
  ]);

  // Keep scrollToBottom identity out of session-reset deps: virtual itemCount
  // changes every message and would re-disarm canLoadOlder permanently.
  const scrollToBottomRef = useRef(scrollToBottom);
  scrollToBottomRef.current = scrollToBottom;

  useEffect(() => {
    setUseVirtualLocked(false);
    loadMoreRequestedRef.current = false;
    canLoadOlderRef.current = nextCanLoadOlder({
      kind: "session-reset",
      loading: !!loading,
      messageCount: messages.length,
    });
    atTopRef.current = false;
    lastSmoothScrolledUserIdRef.current = null;
    scrollHeightBeforePrependRef.current = null;
    prependAnchorIdRef.current = null;
    setFirstItemIndex(VIRTUOSO_START_INDEX);
    scrollToBottomRef.current(true);
    // Intentionally only sessionKey — see scrollToBottomRef above.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- session switch only
  }, [stableSessionKey]);

  // Re-arm after session reset (must run after the effect above).
  useEffect(() => {
    if (
      nextCanLoadOlder({
        kind: "history-ready",
        loading: !!loading,
        messageCount: messages.length,
      })
    ) {
      canLoadOlderRef.current = true;
    }
  }, [loading, messages.length, stableSessionKey]);

  // When the list does not overflow, scroll-to-top never fires — keep loading
  // older pages until content can scroll or the server says there is no more.
  // Do not gate on isStreaming: load-earlier must work during an in-flight reply.
  useEffect(() => {
    if (
      !shouldAutoFillOlderHistory({
        historyHasMore: Boolean(historyHasMore),
        historyLoadingMore: Boolean(historyLoadingMore),
        loading: Boolean(loading),
        canLoadOlder: canLoadOlderRef.current,
      })
    ) {
      return;
    }
    const scroller = useVirtual ? scrollerRef.current : containerRef.current;
    if (!(scroller instanceof HTMLElement)) return;
    if (scroller.scrollHeight <= scroller.clientHeight + 80) {
      requestOlderMessages();
    }
  }, [
    historyHasMore,
    historyLoadingMore,
    loading,
    messages.length,
    useVirtual,
    scrollerMountKey,
    requestOlderMessages,
  ]);

  useEffect(() => {
    if (messageGroups.length >= VIRTUALIZE_THRESHOLD) {
      setUseVirtualLocked(true);
    }
  }, [messageGroups.length]);

  useLayoutEffect(() => {
    // First paint after history arrives: pin before the browser paints the
    // top-of-thread frame (avoids a visible top→bottom jump on refresh).
    if (messages.length === 0) return;
    if (!(prevInitialLoadingRef.current || loading)) return;
    const scroller = useVirtual ? scrollerRef.current : containerRef.current;
    if (scroller instanceof HTMLElement) {
      armProgrammaticGuard(320);
      scroller.scrollTop = scroller.scrollHeight;
    } else {
      scrollToBottomRef.current(true);
    }
    prevInitialLoadingRef.current = !!loading;
  }, [loading, messages.length, useVirtual, armProgrammaticGuard]);

  useEffect(() => {
    prevInitialLoadingRef.current = !!loading;
  }, [loading]);

  // On send: pin instantly in layout so the new user bubble is visible before
  // paint. A deferred smooth scroll left a frame where the message was below
  // the fold, then animated the list upward.
  useLayoutEffect(() => {
    if (!isStreaming) {
      lastSmoothScrolledUserIdRef.current = null;
      return;
    }

    const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUserMsg) return;
    if (lastSmoothScrolledUserIdRef.current === lastUserMsg.id) return;
    lastSmoothScrolledUserIdRef.current = lastUserMsg.id;

    skipNextDepsScrollRef.current = true;
    scrollToBottom(true, true);
  }, [isStreaming, messages, scrollToBottom]);

  // 只让「刚刚出现」的尾部消息做入场，历史载入 / 重连刷新整体不播。
  const groupKeys = useMemo(
    () =>
      messageGroups.map(
        (group, index) => group.messages[0]?.id ?? `g-${index}`,
      ),
    [messageGroups],
  );
  const freshGroupKeys = useNewIds(groupKeys, stableSessionKey, 2);

  const groupContext = useMemo<GroupRenderContext>(
    () => ({
      agentId,
      threadId: sessionKey ?? null,
      composerLookups,
      isStreaming,
      liveSpeakers,
      lastBrowserGroupIndex,
      lastAssistantGroupIndex,
      lastUserGroupIndex,
      onRegenerate,
      onDisableStreamUsage,
      onEditUserMessage,
      onWithdrawSteer,
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
      compactProcess,
      registerBubbleRef,
      freshGroupKeys,
    }),
    [
      agentId,
      composerLookups,
      isStreaming,
      liveSpeakers,
      lastBrowserGroupIndex,
      lastAssistantGroupIndex,
      lastUserGroupIndex,
      onRegenerate,
      onDisableStreamUsage,
      onEditUserMessage,
      onWithdrawSteer,
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
      compactProcess,
      registerBubbleRef,
      freshGroupKeys,
      sessionKey,
    ],
  );

  const footer = useMemo(
    () => (
      <>
        {showGenerating && (
          <div className={styles.generatingSlot}>
            <GeneratingIndicator
              phase={isAwaitingAssistantReply ? "thinking" : "working"}
              startedAt={thinkingStartedAt}
              showElapsed={isAwaitingAssistantReply}
              membersOnly={generatingMembersOnly}
              speakerNames={liveSpeakerNames}
              showAvatar={isAwaitingAssistantReply}
              agentId={agentId}
            />
          </div>
        )}
        {refreshFooter}
      </>
    ),
    [
      showGenerating,
      thinkingStartedAt,
      isAwaitingAssistantReply,
      generatingMembersOnly,
      liveSpeakerNames,
      agentId,
      refreshFooter,
    ],
  );

  const hasFooter = showGenerating || Boolean(refreshFooter);

  const virtuosoContext = useMemo<VirtuosoListContext>(
    () => ({
      historyHeader,
      footer: hasFooter ? footer : null,
    }),
    [historyHeader, hasFooter, footer],
  );

  // History first paint uses a loading spinner with no scroll node. When messages
  // arrive the list mounts; bump scrollerMountKey so useAutoScroll re-binds
  // wheel/scroll listeners (deps would otherwise stay stale after a null bind).
  const bindNonVirtualScroller = useCallback((el: HTMLDivElement | null) => {
    containerRef.current = el;
    if (el) {
      setScrollerMountKey((k) => k + 1);
    }
  }, []);

  if (loading && messages.length === 0) {
    return (
      <div className={styles.messageListWrapper}>
        <div
          className={styles.messageSkeleton}
          role="status"
          aria-busy="true"
          aria-label={t("chat.loadingMessages", "正在加载消息")}
        >
          <div
            className={cx(
              styles.messageSkeletonRow,
              styles.messageSkeletonRowUser,
            )}
          >
            <div className={styles.messageSkeletonBody}>
              <div
                className={styles.messageSkeletonBubble}
                style={{ width: "64%", marginLeft: "36%" }}
              />
            </div>
          </div>
          <div className={styles.messageSkeletonRow}>
            <div className={styles.messageSkeletonAvatar} />
            <div className={styles.messageSkeletonBody}>
              <div
                className={styles.messageSkeletonLine}
                style={{ width: "92%" }}
              />
              <div
                className={styles.messageSkeletonLine}
                style={{ width: "78%" }}
              />
              <div
                className={styles.messageSkeletonLine}
                style={{ width: "46%" }}
              />
            </div>
          </div>
          <div
            className={cx(
              styles.messageSkeletonRow,
              styles.messageSkeletonRowUser,
            )}
          >
            <div className={styles.messageSkeletonBody}>
              <div
                className={styles.messageSkeletonBubble}
                style={{ width: "48%", marginLeft: "52%", height: 30 }}
              />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div ref={wrapperRef} className={styles.messageListWrapper}>
      <TurnTimelineRail
        messages={messages}
        messageGroups={messageGroups}
        isStreaming={isStreaming}
        following={!showScrollBtn}
        useVirtual={useVirtual}
        firstItemIndex={firstItemIndex}
        scrollerRef={scrollerRef}
        containerRef={containerRef}
        virtuosoRef={virtuosoRef}
        bubbleRefsMap={bubbleRefsMap}
        wrapperRef={wrapperRef}
        armProgrammaticGuard={armProgrammaticGuard}
        onVisibilityChange={onTurnRailVisibilityChange}
      />
      {useVirtual ? (
        <Virtuoso
          key={stableSessionKey}
          ref={virtuosoRef}
          className={styles.messageList}
          style={{ height: "100%" }}
          data={messageGroups}
          context={virtuosoContext}
          firstItemIndex={firstItemIndex}
          initialTopMostItemIndex={
            messageGroups.length === 0
              ? firstItemIndex
              : firstItemIndex + messageGroups.length - 1
          }
          increaseViewportBy={{ top: 600, bottom: 800 }}
          followOutput={false}
          atBottomStateChange={handleAtBottomChange}
          atTopStateChange={handleAtTopStateChange}
          atTopThreshold={200}
          startReached={requestOlderMessages}
          scrollerRef={(el) => {
            const next = el instanceof HTMLElement ? el : null;
            if (next !== scrollerRef.current) {
              scrollerRef.current = next;
              if (next) setScrollerMountKey((k) => k + 1);
            }
          }}
          components={virtuosoComponents}
          itemContent={(index, group) =>
            renderMessageGroup(group, index - firstItemIndex, groupContext)
          }
        />
      ) : (
        <div className={styles.messageList} ref={bindNonVirtualScroller}>
          <div className={styles.messageListInner}>
            {historyHeader}
            {messageGroups.map((group, groupIndex) => (
              // Stable key: first message id only. Joining all ids remounts the
              // whole assistant turn whenever a tool/thinking bubble is appended.
              <div key={group.messages[0]?.id ?? `g-${groupIndex}`}>
                {renderMessageGroup(group, groupIndex, groupContext)}
              </div>
            ))}
            {footer}
            <div ref={endRef} style={{ height: 1 }} aria-hidden="true" />
          </div>
        </div>
      )}

      <ScrollToBottomButton
        visible={showScrollBtn}
        hasNewActivity={Boolean(isStreaming || hasLiveSpeakers)}
        onClick={() => scrollToBottom()}
      />
    </div>
  );
}
